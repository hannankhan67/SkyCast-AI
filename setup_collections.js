// SkyCast AI — MongoDB collection setup (run in mongosh / Compass MongoSH)
// Creates the three collections used by the Health, Event Planner and
// Developer API features, with JSON-Schema validation and indexes.

// Switch to your database (edit the name if different)
use skycast_db;

// ====================================================================
// 1. COLLECTION: user_health_thresholds
// ====================================================================
db.createCollection("user_health_thresholds", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["user_id"],
      properties: {
        user_id: { bsonType: "objectId", description: "Reference to users collection" },
        migraine: {
          bsonType: "object",
          properties: {
            enabled: { bsonType: "bool" },
            pressure_drop_hpa: { bsonType: "double" }
          }
        },
        asthma: {
          bsonType: "object",
          properties: {
            enabled: { bsonType: "bool" },
            pm25_threshold: { bsonType: "double" },
            humidity_max: { bsonType: "double" }
          }
        },
        joint_pain: {
          bsonType: "object",
          properties: {
            enabled: { bsonType: "bool" },
            temp_drop_c: { bsonType: "double" }
          }
        },
        uv_safety: {
          bsonType: "object",
          properties: {
            enabled: { bsonType: "bool" },
            max_uv: { bsonType: "double" },
            skin_type_fitzpatrick: { bsonType: "int" }
          }
        },
        updated_at: { bsonType: "date" }
      }
    }
  }
});

// Unique index: one health threshold profile per user
db.user_health_thresholds.createIndex({ user_id: 1 }, { unique: true });

// ====================================================================
// 2. COLLECTION: event_plans
// ====================================================================
db.createCollection("event_plans", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["event_type", "target_city", "event_date", "feasibility_score"],
      properties: {
        user_id: { bsonType: ["objectId", "null"] },
        event_type: { bsonType: "string" },
        event_name: { bsonType: "string" },
        target_city: { bsonType: "string" },
        event_date: { bsonType: "date" },
        feasibility_score: { bsonType: "int" },
        status_label: { bsonType: "string" },
        forecast_snapshot: {
          bsonType: "object",
          properties: {
            temp_c: { bsonType: "double" },
            rain_prob: { bsonType: "double" },
            wind_speed_kmh: { bsonType: "double" },
            cloud_cover_pct: { bsonType: "double" }
          }
        },
        created_at: { bsonType: "date" }
      }
    }
  }
});

db.event_plans.createIndex({ user_id: 1, event_date: -1 });
db.event_plans.createIndex({ target_city: 1 });

// ====================================================================
// 3. COLLECTION: api_key_telemetry
// ====================================================================
db.createCollection("api_key_telemetry");

db.api_key_telemetry.createIndex({ api_key_hash: 1, timestamp: -1 });
db.api_key_telemetry.createIndex({ status_code: 1 });
db.api_key_telemetry.createIndex({ timestamp: 1 }, { expireAfterSeconds: 2592000 });

print("SkyCast collections created: user_health_thresholds, event_plans, api_key_telemetry");
