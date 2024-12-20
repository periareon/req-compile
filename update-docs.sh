#!/bin/bash

bazel build //docs
cp bazel-bin/docs/generated_docs.md docs/docs.md
