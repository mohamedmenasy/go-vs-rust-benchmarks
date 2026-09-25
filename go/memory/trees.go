package main

import (
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// binarytrees: the Benchmarks Game allocation benchmark, single-threaded.
// A long-lived tree of depth D stays alive while many short-lived trees of
// depth 4, 6, ..., D are built, walked and discarded.
type node struct{ left, right *node }

func bottomUp(depth int) *node {
	if depth <= 0 {
		return &node{}
	}
	return &node{left: bottomUp(depth - 1), right: bottomUp(depth - 1)}
}

func (n *node) check() uint64 {
	if n.left == nil {
		return 1
	}
	return 1 + n.left.check() + n.right.check()
}

type treesW struct{ depth int }

const minDepth = 4

func (w *treesW) Run() uint64 {
	maxDepth := w.depth
	d := common.NewDigest()
	d.Add(bottomUp(maxDepth + 1).check()) // stretch tree
	longLived := bottomUp(maxDepth)
	for depth := minDepth; depth <= maxDepth; depth += 2 {
		iters := 1 << (maxDepth - depth + minDepth)
		var check uint64
		for i := 0; i < iters; i++ {
			check += bottomUp(depth).check()
		}
		d.Add(uint64(iters))
		d.Add(uint64(depth))
		d.Add(check)
	}
	d.Add(longLived.check())
	return d.Sum()
}

func (w *treesW) Teardown() { release() }

// treeNodes counts every node allocated by one Run.
func treeNodes(maxDepth int) float64 {
	nodes := func(d int) float64 { return float64(uint64(1)<<(d+1) - 1) }
	total := nodes(maxDepth+1) + nodes(maxDepth)
	for depth := minDepth; depth <= maxDepth; depth += 2 {
		total += float64(uint64(1)<<(maxDepth-depth+minDepth)) * nodes(depth)
	}
	return total
}

func setupTrees(p harness.Params) (harness.Instance, harness.Work, error) {
	depth := int(p.Int("depth", 18))
	return &treesW{depth: depth}, harness.Work{Unit: "nodes", PerRun: treeNodes(depth)}, nil
}
