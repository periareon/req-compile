"""Forward the entrypoint to qer.cmdline to allow running via python -m qer"""
import qer.cmdline

if __name__ == '__main__':
    qer.cmdline.compile_main()
