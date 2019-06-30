import timeit

import scripts.run_dists

if __name__ == '__main__':
    # print('Add source')
    # print(timeit.timeit(stmt="scripts.run_dists.run_add_source()",
    #                     setup="import scripts.run_dists; scripts.run_dists.setup()",
    #                     number=5000))
    print('Build constraints')
    print(timeit.timeit(stmt="scripts.run_dists.run_build_constraints()",
                        setup="import scripts.run_dists; scripts.run_dists.setup_build_constraints()",
                        number=10000))
