"""测试 Kafka 连接"""
import socket
import sys

BOOTSTRAP_SERVERS = '10.20.144.118'
BOOTSTRAP_PORT = 9092

def test_tcp():
    print(f"[1] 测试 TCP 连接: {BOOTSTRAP_SERVERS}:{BOOTSTRAP_PORT}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((BOOTSTRAP_SERVERS, BOOTSTRAP_PORT))
        print("[OK] TCP 连接成功")
        sock.close()
        return True
    except Exception as e:
        print(f"[FAIL] TCP 连接失败: {e}")
        return False

def test_kafka_admin():
    try:
        from kafka import KafkaAdminClient
        print(f"[2] 测试 Kafka AdminClient")
        admin = KafkaAdminClient(
            bootstrap_servers=f'{BOOTSTRAP_SERVERS}:{BOOTSTRAP_PORT}',
            request_timeout_ms=15000,
            api_version=(2, 6, 0),
        )
        topics = admin.list_topics()
        print(f"[OK] 获取 topic 列表成功: {topics}")
        admin.close()
        return True
    except Exception as e:
        print(f"[FAIL] AdminClient 失败: {type(e).__name__} - {e}")
        return False

def test_kafka_producer():
    try:
        from kafka import KafkaProducer
        import json

        print(f"[3] 测试 Kafka Producer 发送消息")
        producer = KafkaProducer(
            bootstrap_servers=f'{BOOTSTRAP_SERVERS}:{BOOTSTRAP_PORT}',
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            request_timeout_ms=15000,
            api_version=(2, 6, 0),
        )

        test_message = {'test': 'hello', 'timestamp': '2026-05-29'}
        future = producer.send('test.connection', test_message)
        result = future.get(timeout=15)
        print(f"[OK] 消息发送成功: topic={result.topic}, partition={result.partition}, offset={result.offset}")

        producer.close()
        return True
    except Exception as e:
        print(f"[FAIL] Producer 发送失败: {type(e).__name__} - {e}")
        return False

if __name__ == "__main__":
    tcp_ok = test_tcp()
    if tcp_ok:
        admin_ok = test_kafka_admin()
        producer_ok = test_kafka_producer()
        if admin_ok or producer_ok:
            print("\n[RESULT] Kafka 连接正常")
            sys.exit(0)
        else:
            print("\n[RESULT] Kafka 连接异常")
            sys.exit(1)
    else:
        sys.exit(1)
