/*
 * Nova FX — Vulkan compute backend (feasibility stage).
 *
 * libvulkan is loaded at runtime (dlopen), so the core still loads on machines without Vulkan.
 * Shaders are compiled to SPIR-V at build time (glslc) and embedded from shaders_spv.h.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>

#include "shaders_spv.h"

#define API __attribute__((visibility("default")))

#define VK_FUNCS(X)                                                                                \
  X(vkDestroyInstance) X(vkEnumeratePhysicalDevices) X(vkGetPhysicalDeviceProperties)               \
  X(vkGetPhysicalDeviceQueueFamilyProperties) X(vkGetPhysicalDeviceMemoryProperties) X(vkCreateDevice) \
  X(vkDestroyDevice) X(vkGetDeviceQueue) X(vkCreateBuffer) X(vkDestroyBuffer)                         \
  X(vkGetBufferMemoryRequirements) X(vkAllocateMemory) X(vkFreeMemory) X(vkBindBufferMemory)          \
  X(vkMapMemory) X(vkUnmapMemory) X(vkCreateShaderModule) X(vkDestroyShaderModule)                   \
  X(vkCreateDescriptorSetLayout) X(vkDestroyDescriptorSetLayout) X(vkCreatePipelineLayout)           \
  X(vkDestroyPipelineLayout) X(vkCreateComputePipelines) X(vkDestroyPipeline)                        \
  X(vkCreateDescriptorPool) X(vkDestroyDescriptorPool) X(vkAllocateDescriptorSets)                   \
  X(vkUpdateDescriptorSets) X(vkCreateCommandPool) X(vkDestroyCommandPool)                           \
  X(vkAllocateCommandBuffers) X(vkBeginCommandBuffer) X(vkEndCommandBuffer) X(vkCmdBindPipeline)     \
  X(vkCmdBindDescriptorSets) X(vkCmdPushConstants) X(vkCmdDispatch) X(vkCmdPipelineBarrier)          \
  X(vkCmdCopyBuffer) X(vkQueueSubmit) X(vkCreateFence) X(vkDestroyFence) X(vkWaitForFences)          \
  X(vkResetFences) X(vkResetCommandBuffer) X(vkDeviceWaitIdle)

static PFN_vkGetInstanceProcAddr vk_gipa;
static PFN_vkCreateInstance vk_create_instance;
#define DECL(f) static PFN_##f f##_;
VK_FUNCS(DECL)
#undef DECL

typedef struct {
  VkBuffer buf;
  VkDeviceMemory mem;
  VkDeviceSize size;
  void *map; /* host-visible buffers only */
} Buf;

static struct {
  int ready, tried;
  char name[256], err[256];
  void *lib;
  VkInstance inst;
  VkPhysicalDevice phys;
  VkPhysicalDeviceMemoryProperties memp;
  VkDevice dev;
  VkQueue queue;
  uint32_t qfam;
  VkCommandPool pool;
  VkCommandBuffer cmd;
  VkFence fence;
  /* advect_scalar pipeline */
  VkDescriptorSetLayout dsl;
  VkPipelineLayout pl;
  VkPipeline pipe;
  VkDescriptorPool dpool;
  VkDescriptorSet ds;
} G;

static double now_ms(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}

static int fail(const char *what, VkResult r) {
  snprintf(G.err, sizeof G.err, "%s failed (VkResult %d)", what, (int)r);
  return -1;
}

static int load(void) {
  G.lib = dlopen("libvulkan.so.1", RTLD_NOW | RTLD_LOCAL);
  if (!G.lib) G.lib = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
  if (!G.lib) {
    snprintf(G.err, sizeof G.err, "libvulkan not found");
    return -1;
  }
  vk_gipa = (PFN_vkGetInstanceProcAddr)dlsym(G.lib, "vkGetInstanceProcAddr");
  vk_create_instance = (PFN_vkCreateInstance)vk_gipa(NULL, "vkCreateInstance");
  return vk_gipa && vk_create_instance ? 0 : -1;
}

static int load_instance_funcs(void) {
#define LOAD(f)                                                  \
  f##_ = (PFN_##f)vk_gipa(G.inst, #f);                           \
  if (!f##_) {                                                   \
    snprintf(G.err, sizeof G.err, "missing Vulkan function %s", #f); \
    return -1;                                                   \
  }
  VK_FUNCS(LOAD)
#undef LOAD
  return 0;
}

static int mem_type(uint32_t bits, VkMemoryPropertyFlags want) {
  for (uint32_t i = 0; i < G.memp.memoryTypeCount; i++)
    if ((bits & (1u << i)) && (G.memp.memoryTypes[i].propertyFlags & want) == want) return (int)i;
  return -1;
}

static int buf_create(Buf *b, VkDeviceSize size, int host) {
  memset(b, 0, sizeof *b);
  VkBufferCreateInfo bi = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
  bi.size = size ? size : 4;
  bi.usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT;
  bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
  VkResult r = vkCreateBuffer_(G.dev, &bi, NULL, &b->buf);
  if (r) return fail("vkCreateBuffer", r);
  VkMemoryRequirements req;
  vkGetBufferMemoryRequirements_(G.dev, b->buf, &req);
  int t = host ? mem_type(req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT |
                                                  VK_MEMORY_PROPERTY_HOST_CACHED_BIT)
               : mem_type(req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
  if (t < 0 && host)
    t = mem_type(req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
  if (t < 0) return fail("memory type", VK_ERROR_FEATURE_NOT_PRESENT);
  VkMemoryAllocateInfo ai = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
  ai.allocationSize = req.size;
  ai.memoryTypeIndex = (uint32_t)t;
  r = vkAllocateMemory_(G.dev, &ai, NULL, &b->mem);
  if (r) return fail("vkAllocateMemory", r);
  vkBindBufferMemory_(G.dev, b->buf, b->mem, 0);
  b->size = bi.size;
  if (host) vkMapMemory_(G.dev, b->mem, 0, VK_WHOLE_SIZE, 0, &b->map);
  return 0;
}

static void buf_free(Buf *b) {
  if (!b->buf) return;
  if (b->map) vkUnmapMemory_(G.dev, b->mem);
  vkDestroyBuffer_(G.dev, b->buf, NULL);
  vkFreeMemory_(G.dev, b->mem, NULL);
  memset(b, 0, sizeof *b);
}

static VkPipeline make_pipeline(const uint32_t *code, size_t bytes, VkPipelineLayout pl) {
  VkShaderModuleCreateInfo si = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
  si.codeSize = bytes;
  si.pCode = code;
  VkShaderModule mod;
  if (vkCreateShaderModule_(G.dev, &si, NULL, &mod)) return VK_NULL_HANDLE;
  VkComputePipelineCreateInfo ci = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
  ci.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
  ci.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
  ci.stage.module = mod;
  ci.stage.pName = "main";
  ci.layout = pl;
  VkPipeline p = VK_NULL_HANDLE;
  vkCreateComputePipelines_(G.dev, VK_NULL_HANDLE, 1, &ci, NULL, &p);
  vkDestroyShaderModule_(G.dev, mod, NULL);
  return p;
}

API int nv_gpu_init(void) {
  if (G.tried) return G.ready ? 0 : -1;
  G.tried = 1;
  if (load()) return -1;
  VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO};
  app.pApplicationName = "Nova FX";
  app.apiVersion = VK_API_VERSION_1_1;
  VkInstanceCreateInfo ii = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
  ii.pApplicationInfo = &app;
  VkResult r = vk_create_instance(&ii, NULL, &G.inst);
  if (r) return fail("vkCreateInstance", r);
  if (load_instance_funcs()) return -1;
  uint32_t n = 0;
  vkEnumeratePhysicalDevices_(G.inst, &n, NULL);
  if (!n) return fail("no Vulkan device", VK_ERROR_INITIALIZATION_FAILED);
  VkPhysicalDevice devs[16];
  if (n > 16) n = 16;
  vkEnumeratePhysicalDevices_(G.inst, &n, devs);
  /* prefer a discrete GPU */
  int best = 0;
  for (uint32_t i = 0; i < n; i++) {
    VkPhysicalDeviceProperties p;
    vkGetPhysicalDeviceProperties_(devs[i], &p);
    if (p.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU) { best = (int)i; break; }
  }
  G.phys = devs[best];
  VkPhysicalDeviceProperties props;
  vkGetPhysicalDeviceProperties_(G.phys, &props);
  snprintf(G.name, sizeof G.name, "%s", props.deviceName);
  vkGetPhysicalDeviceMemoryProperties_(G.phys, &G.memp);
  uint32_t nq = 0;
  vkGetPhysicalDeviceQueueFamilyProperties_(G.phys, &nq, NULL);
  VkQueueFamilyProperties qf[32];
  if (nq > 32) nq = 32;
  vkGetPhysicalDeviceQueueFamilyProperties_(G.phys, &nq, qf);
  G.qfam = UINT32_MAX;
  for (uint32_t i = 0; i < nq; i++) /* a compute-only queue if there is one, else any with compute */
    if ((qf[i].queueFlags & VK_QUEUE_COMPUTE_BIT) && !(qf[i].queueFlags & VK_QUEUE_GRAPHICS_BIT)) { G.qfam = i; break; }
  for (uint32_t i = 0; i < nq && G.qfam == UINT32_MAX; i++)
    if (qf[i].queueFlags & VK_QUEUE_COMPUTE_BIT) G.qfam = i;
  if (G.qfam == UINT32_MAX) return fail("no compute queue", VK_ERROR_FEATURE_NOT_PRESENT);
  float prio = 1.f;
  VkDeviceQueueCreateInfo qi = {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
  qi.queueFamilyIndex = G.qfam;
  qi.queueCount = 1;
  qi.pQueuePriorities = &prio;
  VkDeviceCreateInfo di = {VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
  di.queueCreateInfoCount = 1;
  di.pQueueCreateInfos = &qi;
  r = vkCreateDevice_(G.phys, &di, NULL, &G.dev);
  if (r) return fail("vkCreateDevice", r);
  vkGetDeviceQueue_(G.dev, G.qfam, 0, &G.queue);
  VkCommandPoolCreateInfo pi = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
  pi.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
  pi.queueFamilyIndex = G.qfam;
  vkCreateCommandPool_(G.dev, &pi, NULL, &G.pool);
  VkCommandBufferAllocateInfo ca = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
  ca.commandPool = G.pool;
  ca.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
  ca.commandBufferCount = 1;
  vkAllocateCommandBuffers_(G.dev, &ca, &G.cmd);
  VkFenceCreateInfo fi = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
  vkCreateFence_(G.dev, &fi, NULL, &G.fence);
  /* advect_scalar: 8 storage buffers + push constants */
  VkDescriptorSetLayoutBinding b[8];
  for (int i = 0; i < 8; i++) {
    memset(&b[i], 0, sizeof b[i]);
    b[i].binding = (uint32_t)i;
    b[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    b[i].descriptorCount = 1;
    b[i].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
  }
  VkDescriptorSetLayoutCreateInfo li = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
  li.bindingCount = 8;
  li.pBindings = b;
  vkCreateDescriptorSetLayout_(G.dev, &li, NULL, &G.dsl);
  VkPushConstantRange pcr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, 20};
  VkPipelineLayoutCreateInfo pli = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
  pli.setLayoutCount = 1;
  pli.pSetLayouts = &G.dsl;
  pli.pushConstantRangeCount = 1;
  pli.pPushConstantRanges = &pcr;
  vkCreatePipelineLayout_(G.dev, &pli, NULL, &G.pl);
  G.pipe = make_pipeline(spv_advect_scalar, sizeof spv_advect_scalar, G.pl);
  if (!G.pipe) return fail("pipeline", VK_ERROR_INITIALIZATION_FAILED);
  VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 8};
  VkDescriptorPoolCreateInfo dpi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
  dpi.maxSets = 1;
  dpi.poolSizeCount = 1;
  dpi.pPoolSizes = &ps;
  vkCreateDescriptorPool_(G.dev, &dpi, NULL, &G.dpool);
  VkDescriptorSetAllocateInfo dai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
  dai.descriptorPool = G.dpool;
  dai.descriptorSetCount = 1;
  dai.pSetLayouts = &G.dsl;
  vkAllocateDescriptorSets_(G.dev, &dai, &G.ds);
  G.ready = 1;
  return 0;
}

API const char *nv_gpu_name(void) { return G.ready ? G.name : G.err; }

static void submit_wait(void) {
  VkSubmitInfo si = {VK_STRUCTURE_TYPE_SUBMIT_INFO};
  si.commandBufferCount = 1;
  si.pCommandBuffers = &G.cmd;
  vkQueueSubmit_(G.queue, 1, &si, G.fence);
  vkWaitForFences_(G.dev, 1, &G.fence, VK_TRUE, UINT64_MAX);
  vkResetFences_(G.dev, 1, &G.fence);
}

static void begin(void) {
  vkResetCommandBuffer_(G.cmd, 0);
  VkCommandBufferBeginInfo bi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
  bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
  vkBeginCommandBuffer_(G.cmd, &bi);
}

static void barrier(void) {
  VkMemoryBarrier mb = {VK_STRUCTURE_TYPE_MEMORY_BARRIER};
  mb.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT | VK_ACCESS_TRANSFER_WRITE_BIT;
  mb.dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT | VK_ACCESS_TRANSFER_READ_BIT;
  vkCmdPipelineBarrier_(G.cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT,
                        VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 1, &mb, 0, NULL, 0,
                        NULL);
}

/* Feasibility benchmark: MacCormack advection of one scalar on the GPU.
 * t[0] upload ms, t[1] compute ms per iteration (both passes), t[2] download ms. */
API int nv_gpu_bench_advect(int nx, int ny, int nz, float h, const float *u, const float *v, const float *w,
                            const float *src, float *out, int iters, double *t) {
  if (nv_gpu_init()) return -1;
  size_t nc = (size_t)nx * ny * nz, nu = (size_t)(nx + 1) * ny * nz, nv = (size_t)nx * (ny + 1) * nz,
         nw = (size_t)nx * ny * (nz + 1);
  size_t sizes[8] = {nu, nv, nw, nc, nc, nc, nc, nc};
  Buf d[8], stage;
  size_t stage_bytes = (nu + nv + nw + nc) * 4;
  if (buf_create(&stage, stage_bytes, 1)) return -1;
  for (int i = 0; i < 8; i++)
    if (buf_create(&d[i], sizes[i] * 4, 0)) return -1;
  double t0 = now_ms();
  char *m = (char *)stage.map;
  memcpy(m, u, nu * 4);
  memcpy(m + nu * 4, v, nv * 4);
  memcpy(m + (nu + nv) * 4, w, nw * 4);
  memcpy(m + (nu + nv + nw) * 4, src, nc * 4);
  begin();
  VkDeviceSize off = 0;
  for (int i = 0; i < 4; i++) {
    VkBufferCopy cp = {off, 0, sizes[i] * 4};
    vkCmdCopyBuffer_(G.cmd, stage.buf, d[i].buf, 1, &cp);
    off += sizes[i] * 4;
  }
  vkEndCommandBuffer_(G.cmd);
  submit_wait();
  t[0] = now_ms() - t0;
  VkDescriptorBufferInfo dbi[8];
  VkWriteDescriptorSet wr[8];
  for (int i = 0; i < 8; i++) {
    dbi[i].buffer = d[i].buf;
    dbi[i].offset = 0;
    dbi[i].range = VK_WHOLE_SIZE;
    memset(&wr[i], 0, sizeof wr[i]);
    wr[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    wr[i].dstSet = G.ds;
    wr[i].dstBinding = (uint32_t)i;
    wr[i].descriptorCount = 1;
    wr[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    wr[i].pBufferInfo = &dbi[i];
  }
  vkUpdateDescriptorSets_(G.dev, 8, wr, 0, NULL);
  struct { int nx, ny, nz, pass; float h; } pc = {nx, ny, nz, 0, h};
  uint32_t gx = (uint32_t)(nx + 7) / 8, gy = (uint32_t)(ny + 7) / 8, gz = (uint32_t)(nz + 3) / 4;
  /* warm-up, then timed */
  for (int rep = 0; rep < 2; rep++) {
    int n = rep ? iters : 1;
    double a = now_ms();
    begin();
    vkCmdBindPipeline_(G.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, G.pipe);
    vkCmdBindDescriptorSets_(G.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, G.pl, 0, 1, &G.ds, 0, NULL);
    for (int it = 0; it < n; it++) {
      pc.pass = 0;
      vkCmdPushConstants_(G.cmd, G.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
      vkCmdDispatch_(G.cmd, gx, gy, gz);
      barrier();
      pc.pass = 1;
      vkCmdPushConstants_(G.cmd, G.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
      vkCmdDispatch_(G.cmd, gx, gy, gz);
      barrier();
    }
    vkEndCommandBuffer_(G.cmd);
    submit_wait();
    if (rep) t[1] = (now_ms() - a) / iters;
  }
  t0 = now_ms();
  begin();
  VkBufferCopy cp = {0, 0, nc * 4};
  vkCmdCopyBuffer_(G.cmd, d[7].buf, stage.buf, 1, &cp);
  vkEndCommandBuffer_(G.cmd);
  submit_wait();
  memcpy(out, stage.map, nc * 4);
  t[2] = now_ms() - t0;
  for (int i = 0; i < 8; i++) buf_free(&d[i]);
  buf_free(&stage);
  return 0;
}
