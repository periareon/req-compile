/**
 * @brief A test demonstrating numpy is consumable from a python dependency.
 */

#include <numpy/numpyconfig.h>

#include <cassert>

int main()
{
    assert(NPY_VERSION == 16777225);
    return 0;
}
