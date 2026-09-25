package main

// Typed document schemas; field order equals the JSON key order so that
// re-encoding reproduces the input byte for byte (mirror of rust/json/src/types.rs).

type Dimensions struct {
	Width  float64 `json:"width"`
	Height float64 `json:"height"`
	Depth  float64 `json:"depth"`
}

type Item struct {
	ID          int64      `json:"id"`
	SKU         string     `json:"sku"`
	Name        string     `json:"name"`
	Description string     `json:"description"`
	Price       float64    `json:"price"`
	Quantity    int64      `json:"quantity"`
	InStock     bool       `json:"in_stock"`
	Rating      float64    `json:"rating"`
	Tags        []string   `json:"tags"`
	Dimensions  Dimensions `json:"dimensions"`
	Supplier    *string    `json:"supplier"`
}

type Meta struct {
	Region    string   `json:"region"`
	CacheHit  bool     `json:"cache_hit"`
	LatencyMs float64  `json:"latency_ms"`
	Tags      []string `json:"tags"`
}

// Response is the json/object-* document: an API response with items.
type Response struct {
	RequestID   string `json:"request_id"`
	Status      string `json:"status"`
	Page        int64  `json:"page"`
	PerPage     int64  `json:"per_page"`
	Total       int64  `json:"total"`
	GeneratedAt string `json:"generated_at"`
	Items       []Item `json:"items"`
	Meta        Meta   `json:"meta"`
}

type Geo struct {
	Lat float64 `json:"lat"`
	Lng float64 `json:"lng"`
}

type Address struct {
	Street string `json:"street"`
	City   string `json:"city"`
	Zip    string `json:"zip"`
	Geo    Geo    `json:"geo"`
}

// User is one element of the json/array-* documents.
type User struct {
	ID        int64    `json:"id"`
	Username  string   `json:"username"`
	Email     string   `json:"email"`
	Age       int64    `json:"age"`
	Score     float64  `json:"score"`
	Active    bool     `json:"active"`
	Roles     []string `json:"roles"`
	Address   Address  `json:"address"`
	CreatedAt string   `json:"created_at"`
	Bio       *string  `json:"bio"`
}
