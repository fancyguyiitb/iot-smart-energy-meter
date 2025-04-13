from influxdb_client import InfluxDBClient
from config import settings

# Initialize InfluxDB Client
influxdb_client = InfluxDBClient(
    url=settings.influxdb_url, token=settings.influxdb_token, org=settings.influxdb_org
)

# Create InfluxDB APIs
write_api = influxdb_client.write_api()
query_api = influxdb_client.query_api()
