package main

import (
	"fmt"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/common"
)

// Digests of decoded documents, identical to rust/json/src/digest.rs and
// scripts/benchctl/golden_workloads.py. Computed only in untimed checks.

func b2u(b bool) uint64 {
	if b {
		return 1
	}
	return 0
}

func addOpt(d *common.Digest, s *string) {
	if s == nil {
		d.Add(0)
		return
	}
	d.Add(1)
	d.AddString(*s)
}

func addTags(d *common.Digest, tags []string) {
	d.Add(uint64(len(tags)))
	for _, t := range tags {
		d.AddString(t)
	}
}

func digestResponse(r *Response) uint64 {
	d := common.NewDigest()
	d.AddString(r.RequestID)
	d.AddString(r.Status)
	d.Add(uint64(r.Page))
	d.Add(uint64(r.PerPage))
	d.Add(uint64(r.Total))
	d.AddString(r.GeneratedAt)
	d.Add(uint64(len(r.Items)))
	for i := range r.Items {
		it := &r.Items[i]
		d.Add(uint64(it.ID))
		d.AddString(it.SKU)
		d.AddString(it.Name)
		d.AddString(it.Description)
		d.AddF64(it.Price)
		d.Add(uint64(it.Quantity))
		d.Add(b2u(it.InStock))
		d.AddF64(it.Rating)
		addTags(&d, it.Tags)
		d.AddF64(it.Dimensions.Width)
		d.AddF64(it.Dimensions.Height)
		d.AddF64(it.Dimensions.Depth)
		addOpt(&d, it.Supplier)
	}
	d.AddString(r.Meta.Region)
	d.Add(b2u(r.Meta.CacheHit))
	d.AddF64(r.Meta.LatencyMs)
	addTags(&d, r.Meta.Tags)
	return d.Sum()
}

func digestUsers(us []User) uint64 {
	d := common.NewDigest()
	d.Add(uint64(len(us)))
	for i := range us {
		u := &us[i]
		d.Add(uint64(u.ID))
		d.AddString(u.Username)
		d.AddString(u.Email)
		d.Add(uint64(u.Age))
		d.AddF64(u.Score)
		d.Add(b2u(u.Active))
		addTags(&d, u.Roles)
		d.AddString(u.Address.Street)
		d.AddString(u.Address.City)
		d.AddString(u.Address.Zip)
		d.AddF64(u.Address.Geo.Lat)
		d.AddF64(u.Address.Geo.Lng)
		d.AddString(u.CreatedAt)
		addOpt(&d, u.Bio)
	}
	return d.Sum()
}

// Order-independent structural digest of an `any` tree. Numbers are float64
// in Go; Rust converts serde_json::Number to f64 for the same bits.
const (
	tagObj   = 1 << 56
	tagArr   = 2 << 56
	tagKey   = 3 << 56
	tagStr   = 4 << 56
	tagNum   = 5 << 56
	tagTrue  = 6 << 56
	tagFalse = 7 << 56
	tagNull  = 8 << 56
)

func digestDynamic(v any) uint64 {
	var u common.Unordered
	var walk func(x any)
	walk = func(x any) {
		switch t := x.(type) {
		case map[string]any:
			u.Add(tagObj ^ uint64(len(t)))
			for k, val := range t {
				u.Add(tagKey ^ common.Fnv1a64String(k))
				walk(val)
			}
		case []any:
			u.Add(tagArr ^ uint64(len(t)))
			for _, val := range t {
				walk(val)
			}
		case string:
			u.Add(tagStr ^ common.Fnv1a64String(t))
		case float64:
			u.Add(tagNum ^ common.F64Bits(t))
		case bool:
			if t {
				u.Add(tagTrue)
			} else {
				u.Add(tagFalse)
			}
		case nil:
			u.Add(tagNull)
		default:
			panic(fmt.Sprintf("unexpected JSON value %T", x))
		}
	}
	walk(v)
	return u.Sum()
}
