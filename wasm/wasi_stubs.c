/* An in-module implementation of the WASI preview1 functions wasi-libc imports.
 *
 * Bazel's `execute_wasm` instantiates a module without any imports, so the
 * interpreter cannot rely on the host for anything. These definitions replace
 * the imports with functions compiled into the module: the standard streams are
 * captured into buffers the shim reads back, the clock is a counter, randomness
 * is a fixed-seed generator so every run hashes identically, and the filesystem
 * is empty. Nothing here performs I/O; the Starlark side does all of it.
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define E_SUCCESS 0
#define E_BADF 8
#define E_INVAL 28
#define E_SPIPE 29
#define E_NOENT 44
#define E_NOSYS 52
#define E_ROFS 69

#define PTR(p) ((void *)(uintptr_t)(uint32_t)(p))

typedef struct {
    char *data;
    size_t len;
    size_t cap;
} buffer_t;

static buffer_t g_stdout;
static buffer_t g_stderr;
static uint64_t g_clock = 1700000000ull * 1000000000ull;
static uint64_t g_rng = 0x9E3779B97F4A7C15ull;
int32_t wasi_stub_exit_code = -1;

static void buffer_append(buffer_t *buf, const void *data, size_t len) {
    if (buf->len + len > buf->cap) {
        size_t cap = buf->cap ? buf->cap * 2 : 4096;
        while (cap < buf->len + len) {
            cap *= 2;
        }
        buf->data = realloc(buf->data, cap);
        buf->cap = cap;
    }
    memcpy(buf->data + buf->len, data, len);
    buf->len += len;
}

const char *wasi_stub_captured(int fd, size_t *len) {
    buffer_t *buf = fd == 1 ? &g_stdout : &g_stderr;
    *len = buf->len;
    return buf->data ? buf->data : "";
}

#define WASI(name) __imported_wasi_snapshot_preview1_##name

int32_t WASI(args_get)(int32_t argv, int32_t argv_buf) {
    (void)argv;
    (void)argv_buf;
    return E_SUCCESS;
}

int32_t WASI(args_sizes_get)(int32_t argc, int32_t argv_buf_size) {
    *(uint32_t *)PTR(argc) = 0;
    *(uint32_t *)PTR(argv_buf_size) = 0;
    return E_SUCCESS;
}

int32_t WASI(environ_get)(int32_t environ, int32_t environ_buf) {
    (void)environ;
    (void)environ_buf;
    return E_SUCCESS;
}

int32_t WASI(environ_sizes_get)(int32_t count, int32_t buf_size) {
    *(uint32_t *)PTR(count) = 0;
    *(uint32_t *)PTR(buf_size) = 0;
    return E_SUCCESS;
}

int32_t WASI(clock_res_get)(int32_t id, int32_t out) {
    (void)id;
    *(uint64_t *)PTR(out) = 1000;
    return E_SUCCESS;
}

int32_t WASI(clock_time_get)(int32_t id, int64_t precision, int32_t out) {
    (void)id;
    (void)precision;
    /* Monotonic and deterministic: a millisecond passes per observation. */
    g_clock += 1000000;
    *(uint64_t *)PTR(out) = g_clock;
    return E_SUCCESS;
}

int32_t WASI(fd_advise)(int32_t fd, int64_t offset, int64_t len, int32_t advice) {
    (void)offset;
    (void)len;
    (void)advice;
    return fd <= 2 ? E_SUCCESS : E_BADF;
}

int32_t WASI(fd_allocate)(int32_t fd, int64_t offset, int64_t len) {
    (void)fd;
    (void)offset;
    (void)len;
    return E_NOSYS;
}

int32_t WASI(fd_close)(int32_t fd) {
    return fd <= 2 ? E_SUCCESS : E_BADF;
}

int32_t WASI(fd_datasync)(int32_t fd) {
    return fd <= 2 ? E_SUCCESS : E_BADF;
}

int32_t WASI(fd_fdstat_get)(int32_t fd, int32_t out) {
    if (fd < 0 || fd > 2) {
        return E_BADF;
    }
    uint8_t *stat = PTR(out);
    memset(stat, 0, 24);
    stat[0] = 2; /* character device */
    uint64_t rights = fd == 0 ? (1ull << 1) /* fd_read */ : (1ull << 6) /* fd_write */;
    memcpy(stat + 8, &rights, sizeof(rights));
    return E_SUCCESS;
}

int32_t WASI(fd_fdstat_set_flags)(int32_t fd, int32_t flags) {
    (void)flags;
    return fd <= 2 ? E_SUCCESS : E_BADF;
}

int32_t WASI(fd_fdstat_set_rights)(int32_t fd, int64_t base, int64_t inheriting) {
    (void)base;
    (void)inheriting;
    return fd <= 2 ? E_SUCCESS : E_BADF;
}

int32_t WASI(fd_filestat_get)(int32_t fd, int32_t out) {
    if (fd < 0 || fd > 2) {
        return E_BADF;
    }
    uint8_t *stat = PTR(out);
    memset(stat, 0, 64);
    stat[16] = 2; /* character device */
    return E_SUCCESS;
}

int32_t WASI(fd_filestat_set_size)(int32_t fd, int64_t size) {
    (void)fd;
    (void)size;
    return E_BADF;
}

int32_t WASI(fd_filestat_set_times)(int32_t fd, int64_t atim, int64_t mtim, int32_t flags) {
    (void)fd;
    (void)atim;
    (void)mtim;
    (void)flags;
    return E_BADF;
}

int32_t WASI(fd_pread)(int32_t fd, int32_t iovs, int32_t iovs_len, int64_t offset, int32_t nread) {
    (void)fd;
    (void)iovs;
    (void)iovs_len;
    (void)offset;
    (void)nread;
    return E_BADF;
}

int32_t WASI(fd_prestat_get)(int32_t fd, int32_t out) {
    (void)fd;
    (void)out;
    return E_BADF; /* No preopened directories: the filesystem is empty. */
}

int32_t WASI(fd_prestat_dir_name)(int32_t fd, int32_t path, int32_t path_len) {
    (void)fd;
    (void)path;
    (void)path_len;
    return E_BADF;
}

int32_t WASI(fd_pwrite)(int32_t fd, int32_t iovs, int32_t iovs_len, int64_t offset, int32_t nwritten) {
    (void)fd;
    (void)iovs;
    (void)iovs_len;
    (void)offset;
    (void)nwritten;
    return E_BADF;
}

int32_t WASI(fd_read)(int32_t fd, int32_t iovs, int32_t iovs_len, int32_t nread) {
    (void)iovs;
    (void)iovs_len;
    if (fd != 0) {
        return E_BADF;
    }
    *(uint32_t *)PTR(nread) = 0; /* stdin is always at end of file */
    return E_SUCCESS;
}

int32_t WASI(fd_readdir)(int32_t fd, int32_t buf, int32_t buf_len, int64_t cookie, int32_t used) {
    (void)fd;
    (void)buf;
    (void)buf_len;
    (void)cookie;
    (void)used;
    return E_BADF;
}

int32_t WASI(fd_renumber)(int32_t from, int32_t to) {
    (void)from;
    (void)to;
    return E_BADF;
}

int32_t WASI(fd_seek)(int32_t fd, int64_t offset, int32_t whence, int32_t newoffset) {
    (void)offset;
    (void)whence;
    (void)newoffset;
    return fd <= 2 ? E_SPIPE : E_BADF;
}

int32_t WASI(fd_sync)(int32_t fd) {
    return fd <= 2 ? E_SUCCESS : E_BADF;
}

int32_t WASI(fd_tell)(int32_t fd, int32_t out) {
    (void)out;
    return fd <= 2 ? E_SPIPE : E_BADF;
}

int32_t WASI(fd_write)(int32_t fd, int32_t iovs, int32_t iovs_len, int32_t nwritten) {
    if (fd != 1 && fd != 2) {
        return E_BADF;
    }
    buffer_t *buf = fd == 1 ? &g_stdout : &g_stderr;
    const uint32_t *iov = PTR(iovs);
    uint32_t total = 0;
    for (int32_t i = 0; i < iovs_len; i++) {
        uint32_t ptr = iov[i * 2];
        uint32_t len = iov[i * 2 + 1];
        buffer_append(buf, PTR(ptr), len);
        total += len;
    }
    *(uint32_t *)PTR(nwritten) = total;
    return E_SUCCESS;
}

int32_t WASI(path_create_directory)(int32_t fd, int32_t path, int32_t path_len) {
    (void)fd;
    (void)path;
    (void)path_len;
    return E_ROFS;
}

int32_t WASI(path_filestat_get)(int32_t fd, int32_t flags, int32_t path, int32_t path_len, int32_t out) {
    (void)fd;
    (void)flags;
    (void)path;
    (void)path_len;
    (void)out;
    return E_NOENT;
}

int32_t WASI(path_filestat_set_times)(int32_t fd, int32_t flags, int32_t path, int32_t path_len, int64_t atim, int64_t mtim, int32_t fstflags) {
    (void)fd;
    (void)flags;
    (void)path;
    (void)path_len;
    (void)atim;
    (void)mtim;
    (void)fstflags;
    return E_ROFS;
}

int32_t WASI(path_link)(int32_t old_fd, int32_t old_flags, int32_t old_path, int32_t old_path_len, int32_t new_fd, int32_t new_path, int32_t new_path_len) {
    (void)old_fd;
    (void)old_flags;
    (void)old_path;
    (void)old_path_len;
    (void)new_fd;
    (void)new_path;
    (void)new_path_len;
    return E_ROFS;
}

int32_t WASI(path_open)(int32_t fd, int32_t dirflags, int32_t path, int32_t path_len, int32_t oflags, int64_t rights_base, int64_t rights_inheriting, int32_t fdflags, int32_t opened_fd) {
    (void)fd;
    (void)dirflags;
    (void)path;
    (void)path_len;
    (void)oflags;
    (void)rights_base;
    (void)rights_inheriting;
    (void)fdflags;
    (void)opened_fd;
    return E_NOENT;
}

int32_t WASI(path_readlink)(int32_t fd, int32_t path, int32_t path_len, int32_t buf, int32_t buf_len, int32_t used) {
    (void)fd;
    (void)path;
    (void)path_len;
    (void)buf;
    (void)buf_len;
    (void)used;
    return E_NOENT;
}

int32_t WASI(path_remove_directory)(int32_t fd, int32_t path, int32_t path_len) {
    (void)fd;
    (void)path;
    (void)path_len;
    return E_ROFS;
}

int32_t WASI(path_rename)(int32_t fd, int32_t old_path, int32_t old_path_len, int32_t new_fd, int32_t new_path, int32_t new_path_len) {
    (void)fd;
    (void)old_path;
    (void)old_path_len;
    (void)new_fd;
    (void)new_path;
    (void)new_path_len;
    return E_ROFS;
}

int32_t WASI(path_symlink)(int32_t old_path, int32_t old_path_len, int32_t fd, int32_t new_path, int32_t new_path_len) {
    (void)old_path;
    (void)old_path_len;
    (void)fd;
    (void)new_path;
    (void)new_path_len;
    return E_ROFS;
}

int32_t WASI(path_unlink_file)(int32_t fd, int32_t path, int32_t path_len) {
    (void)fd;
    (void)path;
    (void)path_len;
    return E_ROFS;
}

int32_t WASI(poll_oneoff)(int32_t in, int32_t out, int32_t nsubscriptions, int32_t nevents) {
    (void)in;
    (void)out;
    (void)nsubscriptions;
    (void)nevents;
    return E_NOSYS;
}

void WASI(proc_exit)(int32_t code) {
    /* Nothing can be returned once the interpreter decides to exit. The shim
     * never lets it get here; record the code and stop. */
    wasi_stub_exit_code = code;
    __builtin_trap();
}

int32_t WASI(random_get)(int32_t buf, int32_t len) {
    uint8_t *out = PTR(buf);
    for (int32_t i = 0; i < len; i++) {
        g_rng ^= g_rng << 13;
        g_rng ^= g_rng >> 7;
        g_rng ^= g_rng << 17;
        out[i] = (uint8_t)g_rng;
    }
    return E_SUCCESS;
}

int32_t WASI(sched_yield)(void) {
    return E_SUCCESS;
}

int32_t WASI(sock_accept)(int32_t fd, int32_t flags, int32_t out) {
    (void)fd;
    (void)flags;
    (void)out;
    return E_BADF;
}

int32_t WASI(sock_recv)(int32_t fd, int32_t ri_data, int32_t ri_data_len, int32_t ri_flags, int32_t ro_datalen, int32_t ro_flags) {
    (void)fd;
    (void)ri_data;
    (void)ri_data_len;
    (void)ri_flags;
    (void)ro_datalen;
    (void)ro_flags;
    return E_BADF;
}

int32_t WASI(sock_send)(int32_t fd, int32_t si_data, int32_t si_data_len, int32_t si_flags, int32_t so_datalen) {
    (void)fd;
    (void)si_data;
    (void)si_data_len;
    (void)si_flags;
    (void)so_datalen;
    return E_BADF;
}

int32_t WASI(sock_shutdown)(int32_t fd, int32_t how) {
    (void)fd;
    (void)how;
    return E_BADF;
}
