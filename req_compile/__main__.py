"""Forward the entrypoint to req_compile.cmdline to allow running via python -m req_compile"""
import req_compile.cmdline

if __name__ == "__main__":
    req_compile.cmdline.compile_main()
