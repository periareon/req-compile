/* The entry points Bazel's `execute_wasm` calls, wrapping an embedded CPython.
 *
 * `allocate` is the allocator Bazel uses to place the input buffer, and `solve`
 * is the function with the signature `execute_wasm` expects. `solve` starts the
 * interpreter, runs the bootstrap that imports from the embedded bundle, hands
 * it the input, and returns whatever the Python entry point produced. Every
 * call is a fresh instance, so there is nothing to tear down.
 */
#include <Python.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

extern const unsigned char bundle_start[];
extern const unsigned char bundle_end[];
extern const char bootstrap_src[];
extern const char *wasi_stub_captured(int fd, size_t *len);

static const uint8_t *g_input;
static size_t g_input_len;
static char *g_output;
static size_t g_output_len;
static int g_output_set;
static uint32_t g_code;

/* Set once the interpreter is up and the entry point imported. When the module
 * was pre-initialized with Wizer this is already 1 when `solve` is first called,
 * and the call skips straight to running the entry point. */
static int g_ready;
static PyObject *g_run;

static PyObject *host_input(PyObject *self, PyObject *args) {
    (void)self;
    (void)args;
    return PyMemoryView_FromMemory((char *)g_input, (Py_ssize_t)g_input_len, PyBUF_READ);
}

static PyObject *host_bundle(PyObject *self, PyObject *args) {
    (void)self;
    (void)args;
    return PyMemoryView_FromMemory((char *)bundle_start, (Py_ssize_t)(bundle_end - bundle_start), PyBUF_READ);
}

static PyObject *host_set_output(PyObject *self, PyObject *args) {
    (void)self;
    Py_buffer view;
    unsigned int code = 0;
    if (!PyArg_ParseTuple(args, "y*|I", &view, &code)) {
        return NULL;
    }
    free(g_output);
    g_output = malloc(view.len ? (size_t)view.len : 1);
    memcpy(g_output, view.buf, (size_t)view.len);
    g_output_len = (size_t)view.len;
    g_output_set = 1;
    g_code = code;
    PyBuffer_Release(&view);
    Py_RETURN_NONE;
}

static PyMethodDef host_methods[] = {
    {"input", host_input, METH_NOARGS, "The input buffer of this call."},
    {"bundle", host_bundle, METH_NOARGS, "The embedded source bundle."},
    {"set_output", host_set_output, METH_VARARGS, "Set the output buffer and return code."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef host_module = {
    PyModuleDef_HEAD_INIT, "_host", NULL, -1, host_methods, NULL, NULL, NULL, NULL,
};

static PyObject *PyInit__host(void) {
    return PyModule_Create(&host_module);
}

__attribute__((export_name("allocate"))) void *wasm_allocate(uint32_t size, uint32_t align) {
    (void)align; /* malloc alignment is sufficient for byte buffers */
    return malloc(size ? size : 1);
}

/* Start the interpreter and import the entry point. Returns NULL on success,
 * else a message; details are on the captured stderr. */
static const char *initialize(void) {
    if (g_ready) {
        return NULL;
    }
    PyImport_AppendInittab("_host", PyInit__host);

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.module_search_paths_set = 1; /* nothing on sys.path: the bundle finder serves imports */
    config.site_import = 0;
    config.write_bytecode = 0;
    config.install_signal_handlers = 0;
    config.pathconfig_warnings = 0;
    config.buffered_stdio = 0;
    config.use_hash_seed = 1;
    config.hash_seed = 0;
    PyConfig_SetString(&config, &config.program_name, L"req-compile");
    PyConfig_SetString(&config, &config.home, L"/req-compile");

    /* Stop after the core phase: the bundle importer must be on sys.meta_path
     * before the main phase imports `encodings`, which this build does not
     * freeze. Only builtin and frozen modules are importable until then, and
     * the bootstrap needs nothing else to install the importer. */
    config._init_main = 0;

    PyStatus status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        return status.err_msg ? status.err_msg : "Python failed to initialize";
    }

    PyObject *globals = PyDict_New();
    PyDict_SetItemString(globals, "__builtins__", PyEval_GetBuiltins());
    PyObject *result = PyRun_String(bootstrap_src, Py_file_input, globals, globals);
    if (result == NULL) {
        PyErr_Clear();
        return "The solver bootstrap failed before the interpreter was fully initialized";
    }
    Py_DECREF(result);

    status = _Py_InitializeMain();
    if (PyStatus_Exception(status)) {
        return status.err_msg ? status.err_msg : "Python failed to initialize (main phase)";
    }

    /* `prepare` imports the entry point and returns the callable that runs it,
     * so that a pre-initialized module has the imports done already. */
    PyObject *prepare = PyDict_GetItemString(globals, "prepare");
    g_run = prepare ? PyObject_CallNoArgs(prepare) : NULL;
    if (g_run == NULL) {
        PyErr_Print();
        return "The solver bootstrap failed";
    }
    g_ready = 1;
    return NULL;
}

/* Wizer calls this once at build time and snapshots the memory afterwards. */
__attribute__((export_name("wizer.initialize"))) void wizer_initialize(void) {
    const char *error = initialize();
    if (error != NULL) {
        size_t len;
        const char *err = wasi_stub_captured(2, &len);
        (void)err;
        __builtin_trap();
    }
}

static uint32_t fail(const char *message, uint8_t **out_ptr, uint32_t *out_len) {
    size_t err_len;
    const char *err = wasi_stub_captured(2, &err_len);
    size_t msg_len = strlen(message);
    char *buf = malloc(msg_len + err_len + 2);
    memcpy(buf, message, msg_len);
    buf[msg_len] = '\n';
    memcpy(buf + msg_len + 1, err, err_len);
    *out_ptr = (uint8_t *)buf;
    *out_len = (uint32_t)(msg_len + 1 + err_len);
    return 2;
}

__attribute__((export_name("solve"))) uint32_t solve(const uint8_t *input, uint32_t input_len, uint8_t **out_ptr, uint32_t *out_len) {
    g_input = input;
    g_input_len = input_len;
    g_output_set = 0;

    const char *error = initialize();
    if (error != NULL) {
        return fail(error, out_ptr, out_len);
    }

    PyObject *result = PyObject_CallNoArgs(g_run);
    if (result == NULL) {
        PyErr_Print();
        return fail("The solver failed", out_ptr, out_len);
    }
    Py_DECREF(result);
    if (!g_output_set) {
        return fail("The solver produced no output", out_ptr, out_len);
    }

    *out_ptr = (uint8_t *)g_output;
    *out_len = (uint32_t)g_output_len;
    return g_code;
}
