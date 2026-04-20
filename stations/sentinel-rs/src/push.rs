use redis::AsyncCommands;
use serde_json::Value;

pub async fn publish(redis_url: &str, channel: &str, payload: &Value) {
    let fut = async {
        let client = redis::Client::open(redis_url)?;
        let mut con = client.get_multiplexed_async_connection().await?;
        let _: i64 = con.publish(channel, payload.to_string()).await?;
        anyhow::Ok(())
    };
    if let Err(e) = tokio::time::timeout(std::time::Duration::from_secs(3), fut).await {
        tracing::warn!("redis publish timeout: {}", e);
    }
}
