package main

import (
	"math"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/harness"
)

// nbody: the Computer Language Benchmarks Game planetary simulation (simple,
// non-SIMD formulation), identical operation order to rust/cpu/src/nbody.rs.

type body struct{ x, y, z, vx, vy, vz, mass float64 }

// Derived constants are computed with run-time float64 arithmetic on purpose:
// Go evaluates constant expressions such as 4*math.Pi*math.Pi exactly and
// rounds once, while Rust (and IEEE arithmetic in general) rounds after every
// operation. Using variables keeps the inputs bit-identical across languages.
var (
	nbPi          = math.Pi
	nbDaysPerYear = 365.24
)

func nbodyInitial() [5]body {
	solarMass := 4.0 * nbPi * nbPi
	dpy := nbDaysPerYear
	bs := [5]body{
		{0, 0, 0, 0, 0, 0, solarMass},
		{4.84143144246472090e+00, -1.16032004402742839e+00, -1.03622044471123109e-01,
			1.66007664274403694e-03 * dpy, 7.69901118419740425e-03 * dpy, -6.90460016972063023e-05 * dpy,
			9.54791938424326609e-04 * solarMass},
		{8.34336671824457987e+00, 4.12479856412430479e+00, -4.03523417114321381e-01,
			-2.76742510726862411e-03 * dpy, 4.99852801234917238e-03 * dpy, 2.30417297573763929e-05 * dpy,
			2.85885980666130812e-04 * solarMass},
		{1.28943695621391310e+01, -1.51111514016986312e+01, -2.23307578892655734e-01,
			2.96460137564761618e-03 * dpy, 2.37847173959480950e-03 * dpy, -2.96589568540237556e-05 * dpy,
			4.36624404335156298e-05 * solarMass},
		{1.53796971148509165e+01, -2.59193146099879641e+01, 1.79258772950371181e-01,
			2.68067772490389322e-03 * dpy, 1.62824170038242295e-03 * dpy, -9.51592254519715870e-05 * dpy,
			5.15138902046611451e-05 * solarMass},
	}
	var px, py, pz float64
	for _, b := range bs {
		px += b.vx * b.mass
		py += b.vy * b.mass
		pz += b.vz * b.mass
	}
	bs[0].vx = -px / solarMass
	bs[0].vy = -py / solarMass
	bs[0].vz = -pz / solarMass
	return bs
}

func nbodyEnergy(bs *[5]body) float64 {
	e := 0.0
	for i := range bs {
		b := &bs[i]
		e += 0.5 * b.mass * (b.vx*b.vx + b.vy*b.vy + b.vz*b.vz)
		for j := i + 1; j < len(bs); j++ {
			b2 := &bs[j]
			dx := b.x - b2.x
			dy := b.y - b2.y
			dz := b.z - b2.z
			e -= (b.mass * b2.mass) / math.Sqrt(dx*dx+dy*dy+dz*dz)
		}
	}
	return e
}

func nbodyAdvance(bs *[5]body, dt float64) {
	for i := 0; i < len(bs); i++ {
		bi := &bs[i]
		for j := i + 1; j < len(bs); j++ {
			bj := &bs[j]
			dx := bi.x - bj.x
			dy := bi.y - bj.y
			dz := bi.z - bj.z
			dsq := dx*dx + dy*dy + dz*dz
			dist := math.Sqrt(dsq)
			mag := dt / (dsq * dist)
			bi.vx -= dx * bj.mass * mag
			bi.vy -= dy * bj.mass * mag
			bi.vz -= dz * bj.mass * mag
			bj.vx += dx * bi.mass * mag
			bj.vy += dy * bi.mass * mag
			bj.vz += dz * bi.mass * mag
		}
	}
	for i := range bs {
		b := &bs[i]
		b.x += dt * b.vx
		b.y += dt * b.vy
		b.z += dt * b.vz
	}
}

type nbodyW struct {
	steps   int
	initial [5]body
	bodies  [5]body
}

func (w *nbodyW) Prepare() { w.bodies = w.initial }

func (w *nbodyW) Run() uint64 {
	e0 := nbodyEnergy(&w.bodies)
	for i := 0; i < w.steps; i++ {
		nbodyAdvance(&w.bodies, 0.01)
	}
	e1 := nbodyEnergy(&w.bodies)
	d := common.NewDigest()
	d.AddF64(e0)
	d.AddF64(e1)
	return d.Sum()
}

func setupNbody(p harness.Params) (harness.Instance, harness.Work, error) {
	steps := int(p.Int("steps", 10_000_000))
	return &nbodyW{steps: steps, initial: nbodyInitial()}, harness.Work{Unit: "steps", PerRun: float64(steps)}, nil
}
