// Shared layout for every Nova FX compute kernel: one descriptor set, fields addressed by offset.
layout(std430, binding = 0) buffer BF { float F[]; };    // all float grids (offsets in push constants)
layout(std430, binding = 1) buffer BFU { uint FU[]; };   // same memory as F, viewed as uint (atomics)
layout(std430, binding = 2) buffer BS { uint S[]; };     // stencils (diag | nb<<8), solid flags, buckets
layout(std430, binding = 3) buffer BR { float R[]; };    // reduction partials and results (host visible)
layout(std430, binding = 4) readonly buffer BP { float PTS[]; };  // source points / deposits
layout(std430, binding = 5) readonly buffer BPI { uint PIDX[]; }; // per-tile point ranges

layout(push_constant) uniform PC {
  ivec4 n;   // nx, ny, nz, op
  uvec4 o0;  // offsets
  uvec4 o1;
  uvec4 o2;
  vec4 f0;   // floats
  vec4 f1;
  vec4 f2;
  uvec4 tl;  // tiled dispatch: (tile list offset in S, -, tile flags offset in S, 1 = on)
} pc;

// ---- tiled dispatch (sparse solver). One workgroup per 8^3 tile listed at S[tl.x]; its invocations
// stride over a box of the tile, which is up to 9 wide on an axis for face arrays. Each kernel says which
// box per op: the cells (tile_box), the faces of one component the tile owns (face_box: the last tile on an
// axis also owns the extra face layer), or all three components at once (faces_union), optionally each
// with the high-side face layer next to a tile outside the pressure region (prs_face_box in nova_core.c).
// Off (tl.w == 0), each invocation handles the one index of the dispatch grid, as before.
// Tile flags at S[tl.z], one byte per tile: 1 advection region, 2 pressure region.
#define TILE_ADV 1u
#define TILE_PRS 2u
struct Box { ivec3 lo, hi; };  // [lo, hi)
bool tiled() { return pc.tl.w != 0u; }
int cur_tile() { return int(S[pc.tl.x + gl_WorkGroupID.x]); }
uint tile_flags(int t) { return (S[pc.tl.z + uint(t >> 2)] >> (8u * uint(t & 3))) & 255u; }
ivec3 tile_count(ivec3 n) { return (n + 7) / 8; }
ivec3 tile_coord(int t, ivec3 nt) { return ivec3(t % nt.x, (t / nt.x) % nt.y, t / (nt.x * nt.y)); }
// cells of tile t in a grid of n cells
Box tile_box(int t, ivec3 n) {
  ivec3 lo = tile_coord(t, tile_count(n)) * 8;
  return Box(lo, min(lo + 8, n));
}
// faces of component c owned by tile t; prs: plus the shared high layer next to a tile outside the region
Box face_box(int t, ivec3 n, int c, bool prs) {
  ivec3 nt = tile_count(n), tc = tile_coord(t, nt);
  Box b = tile_box(t, n);
  if (tc[c] == nt[c] - 1) b.hi[c] = n[c] + 1;
  else if (prs) {
    int nb = t + (c == 0 ? 1 : (c == 1 ? nt.x : nt.x * nt.y));
    if ((tile_flags(nb) & TILE_PRS) == 0u) b.hi[c] += 1;
  }
  return b;
}
bool in_box(ivec3 g, Box b) { return all(greaterThanEqual(g, b.lo)) && all(lessThan(g, b.hi)); }
// loop over a box with a 3D workgroup (g = the index); close with BOX_END
#define BOX_BEGIN(b)                                                                                   \
  for (int k_ = (b).lo.z + int(gl_LocalInvocationID.z); k_ < (b).hi.z; k_ += int(gl_WorkGroupSize.z))  \
    for (int j_ = (b).lo.y + int(gl_LocalInvocationID.y); j_ < (b).hi.y; j_ += int(gl_WorkGroupSize.y)) \
      for (int i_ = (b).lo.x + int(gl_LocalInvocationID.x); i_ < (b).hi.x; i_ += int(gl_WorkGroupSize.x)) { \
        ivec3 g = ivec3(i_, j_, k_);
#define BOX_END }
// the same for a 1D workgroup over the cells of a tile box (at most 8^3)
#define CELLS1D_BEGIN(b)                                                                    \
  for (uint li_ = gl_LocalInvocationIndex; li_ < 512u; li_ += gl_WorkGroupSize.x) {         \
    ivec3 g = (b).lo + ivec3(int(li_ & 7u), int((li_ >> 3) & 7u), int(li_ >> 6));            \
    if (any(greaterThanEqual(g, (b).hi))) continue;
#define CELLS1D_END }
// union of the three face boxes of a tile, with each component's own box
Box faces_union(int t, ivec3 n, bool prs, out Box bu, out Box bv, out Box bw) {
  bu = face_box(t, n, 0, prs); bv = face_box(t, n, 1, prs); bw = face_box(t, n, 2, prs);
  return Box(bu.lo, max(max(bu.hi, bv.hi), bw.hi));
}

uint cidx(int i, int j, int k) { return uint(i + pc.n.x * (j + pc.n.y * k)); }
uint uidx(int i, int j, int k) { return uint(i + (pc.n.x + 1) * (j + pc.n.y * k)); }
uint vidx(int i, int j, int k) { return uint(i + pc.n.x * (j + (pc.n.y + 1) * k)); }
uint widx(int i, int j, int k) { return uint(i + pc.n.x * (j + pc.n.y * k)); }

// clamp-to-edge trilinear sample of a grid stored at F[off] with dims s
float samp_clamp(uint off, ivec3 s, vec3 p) {
  p = clamp(p, vec3(0.0), vec3(s - 1));
  ivec3 b = ivec3(floor(p));
  vec3 t = p - vec3(b);
  float v[8];
  for (int q = 0; q < 8; q++) {
    ivec3 c = clamp(b + ivec3(q & 1, (q >> 1) & 1, (q >> 2) & 1), ivec3(0), s - 1);
    v[q] = F[off + uint(c.x + s.x * (c.y + s.y * c.z))];
  }
  return mix(mix(mix(v[0], v[1], t.x), mix(v[2], v[3], t.x), t.y),
             mix(mix(v[4], v[5], t.x), mix(v[6], v[7], t.x), t.y), t.z);
}

// zero-outside trilinear sample with min/max of the 8 corners
float samp_zero_mm(uint off, ivec3 s, vec3 p, out float lo, out float hi) {
  p = clamp(p, vec3(-1.0), vec3(s));
  ivec3 b = ivec3(floor(p));
  vec3 t = p - vec3(b);
  float v[8];
  for (int q = 0; q < 8; q++) {
    ivec3 c = b + ivec3(q & 1, (q >> 1) & 1, (q >> 2) & 1);
    bool o = any(lessThan(c, ivec3(0))) || any(greaterThanEqual(c, s));
    v[q] = o ? 0.0 : F[off + uint(c.x + s.x * (c.y + s.y * c.z))];
  }
  lo = v[0]; hi = v[0];
  for (int q = 1; q < 8; q++) { lo = min(lo, v[q]); hi = max(hi, v[q]); }
  return mix(mix(mix(v[0], v[1], t.x), mix(v[2], v[3], t.x), t.y),
             mix(mix(v[4], v[5], t.x), mix(v[6], v[7], t.x), t.y), t.z);
}

// clamp sample with min/max (velocity MacCormack)
float samp_clamp_mm(uint off, ivec3 s, vec3 p, out float lo, out float hi) {
  p = clamp(p, vec3(0.0), vec3(s - 1));
  ivec3 b = ivec3(floor(p));
  vec3 t = p - vec3(b);
  float v[8];
  for (int q = 0; q < 8; q++) {
    ivec3 c = clamp(b + ivec3(q & 1, (q >> 1) & 1, (q >> 2) & 1), ivec3(0), s - 1);
    v[q] = F[off + uint(c.x + s.x * (c.y + s.y * c.z))];
  }
  lo = v[0]; hi = v[0];
  for (int q = 1; q < 8; q++) { lo = min(lo, v[q]); hi = max(hi, v[q]); }
  return mix(mix(mix(v[0], v[1], t.x), mix(v[2], v[3], t.x), t.y),
             mix(mix(v[4], v[5], t.x), mix(v[6], v[7], t.x), t.y), t.z);
}

vec3 vel_at(uint U, uint V, uint W, vec3 p) {
  ivec3 n = pc.n.xyz;
  return vec3(samp_clamp(U, ivec3(n.x + 1, n.y, n.z), p - vec3(0.0, 0.5, 0.5)),
              samp_clamp(V, ivec3(n.x, n.y + 1, n.z), p - vec3(0.5, 0.0, 0.5)),
              samp_clamp(W, ivec3(n.x, n.y, n.z + 1), p - vec3(0.5, 0.5, 0.0)));
}

vec3 trace(uint U, uint V, uint W, vec3 p, float h) {
  vec3 v1 = vel_at(U, V, W, p);
  vec3 v2 = vel_at(U, V, W, p - 0.5 * h * v1);
  return p - h * v2;
}

bool is_solid(int i, int j, int k, uint solid_off, bool closed_floor) {
  if (i < 0 || j < 0 || i >= pc.n.x || j >= pc.n.y || k >= pc.n.z) return false;
  if (k < 0) return closed_floor;
  return S[solid_off + cidx(i, j, k)] != 0u;
}
