# pylint: disable=redefined-builtin,invalid-name,unused-argument
# Replacement for __import__()
import imp
import os
import sys


def import_hook(opener, name, globals=None, locals=None, fromlist=None, level=0):
    parent = determine_parent(globals)
    q, tail = find_head_package(opener, parent, name)
    m = load_tail(opener, q, tail)
    if not fromlist:
        return q
    if hasattr(m, "__path__"):
        ensure_fromlist(opener, m, fromlist)
    return m


def determine_parent(globals):
    if not globals or '__name__' not in globals:
        return None
    pname = globals['__name__']
    if '__path__' in globals:
        parent = sys.modules[pname]
        assert globals is parent.__dict__
        return parent
    if '.' in pname:
        i = pname.rfind('.')
        pname = pname[:i]
        parent = sys.modules[pname]
        assert parent.__name__ == pname
        return parent
    return None


def find_head_package(opener, parent, name):
    if '.' in name:
        i = name.find('.')
        head = name[:i]
        tail = name[i + 1:]
    else:
        head = name
        tail = ""
    if parent:
        qname = "%s.%s" % (parent.__name__, head)
    else:
        qname = head
    q = import_module(opener, head, qname, parent)
    if q:
        return q, tail
    if parent:
        qname = head
        parent = None
        q = import_module(opener, head, qname, parent)
        if q:
            return q, tail
    raise ImportError("No module named " + qname)


def load_tail(opener, q, tail):
    m = q
    while tail:
        i = tail.find('.')
        if i < 0:
            i = len(tail)
        head, tail = tail[:i], tail[i + 1:]
        mname = "%s.%s" % (m.__name__, head)
        m = import_module(opener, head, mname, m)
        if not m:
            raise ImportError("No module named " + mname)
    return m


def ensure_fromlist(opener, m, fromlist, recursive=0):
    for sub in fromlist:
        if sub == "*":
            if not recursive:
                try:
                    all = m.__all__
                except AttributeError:
                    pass
                else:
                    ensure_fromlist(opener, m, all, 1)
            continue
        if sub != "*" and not hasattr(m, sub):
            subname = "%s.%s" % (m.__name__, sub)
            submod = import_module(opener, sub, subname, m)
            if not submod:
                raise ImportError("No module named " + subname)


def remove_encoding_lines(contents):
    lines = contents.split('\n')
    lines = [line for line in lines if not (line.startswith('#') and
                                            ('-*- coding' in line or '-*- encoding' in line or 'encoding:' in line))]
    return '\n'.join(lines)


def import_contents(modname, filename, contents):
    module = imp.new_module(modname)
    if filename.endswith('__init__.py'):
        setattr(module, '__path__',
                [os.path.dirname(filename)])
    setattr(module, '__name__', modname)
    setattr(module, '__file__', filename)
    sys.modules[modname] = module
    contents = remove_encoding_lines(contents)
    exec(contents, module.__dict__)  # pylint: disable=exec-used
    return module


def _do_import(opener, modname, paths):
    all_paths = sys.path
    if paths:
        all_paths = paths + all_paths
    for path in all_paths:
        for filename in (os.path.join(path, modname.replace('.', '/') + '.py'),
                         os.path.join(path, modname.replace('.', '/'), '__init__.py')):
            try:
                with opener(filename) as src:
                    contents = src.read()
                    module = import_contents(modname, filename, contents)
                    return module
            except EnvironmentError:
                pass
    return None


def import_module(opener, partname, fqname, parent):
    try:
        return sys.modules[fqname]
    except KeyError:
        pass
    fp = None
    try:
        fp, pathname, stuff = imp.find_module(partname,
                                              parent and parent.__path__)
        m = imp.load_module(fqname, fp, pathname, stuff)
    except AttributeError:
        raise ImportError(partname)
    except ImportError:
        m = _do_import(opener, fqname, parent and parent.__path__)
    finally:
        if fp is not None:
            fp.close()

    if parent and m is not None:
        setattr(parent, partname, m)
    return m
