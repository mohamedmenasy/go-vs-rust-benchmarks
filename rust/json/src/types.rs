//! Typed document schemas; field order equals the JSON key order so that
//! re-encoding reproduces the input byte for byte (mirror of go/json/types.go).

use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
pub struct Dimensions {
    pub width: f64,
    pub height: f64,
    pub depth: f64,
}

#[derive(Serialize, Deserialize)]
pub struct Item {
    pub id: i64,
    pub sku: String,
    pub name: String,
    pub description: String,
    pub price: f64,
    pub quantity: i64,
    pub in_stock: bool,
    pub rating: f64,
    pub tags: Vec<String>,
    pub dimensions: Dimensions,
    pub supplier: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct Meta {
    pub region: String,
    pub cache_hit: bool,
    pub latency_ms: f64,
    pub tags: Vec<String>,
}

/// The json/object-* document: an API response with items.
#[derive(Serialize, Deserialize)]
pub struct Response {
    pub request_id: String,
    pub status: String,
    pub page: i64,
    pub per_page: i64,
    pub total: i64,
    pub generated_at: String,
    pub items: Vec<Item>,
    pub meta: Meta,
}

#[derive(Serialize, Deserialize)]
pub struct Geo {
    pub lat: f64,
    pub lng: f64,
}

#[derive(Serialize, Deserialize)]
pub struct Address {
    pub street: String,
    pub city: String,
    pub zip: String,
    pub geo: Geo,
}

/// One element of the json/array-* documents.
#[derive(Serialize, Deserialize)]
pub struct User {
    pub id: i64,
    pub username: String,
    pub email: String,
    pub age: i64,
    pub score: f64,
    pub active: bool,
    pub roles: Vec<String>,
    pub address: Address,
    pub created_at: String,
    pub bio: Option<String>,
}
