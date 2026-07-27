#!/usr/bin/env python3
"""Diagnostic: scan the tail of all PlatformEvent_v1 partitions and print every
entityChangeEvent found, to determine which change categories GMS actually emits
as EntityChangeEvent_v1 (and for which entity types). Read-only against Kafka."""
import json
import sys

from confluent_kafka import Consumer, TopicPartition
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer
from confluent_kafka.serialization import SerializationContext, MessageField

from datahub.emitter.serialization_helper import post_json_transform
from datahub.metadata.schema_classes import GenericPayloadClass

TAIL_PER_PARTITION = int(sys.argv[1]) if len(sys.argv) > 1 else 15

sr = SchemaRegistryClient({"url": "http://localhost:8090/schema-registry/api/"})
deser = AvroDeserializer(schema_registry_client=sr, return_record_name=True)

c = Consumer({
    "bootstrap.servers": "localhost:9092",
    "group.id": "mnemo-pe-scan-" + str(id(object())),
    "auto.offset.reset": "earliest",
})

for pid in (0, 1, 2):
    tp = TopicPartition("PlatformEvent_v1", pid, 0)
    c.assign([tp])
    c.poll(0.1)
    low, high = c.get_watermark_offsets(TopicPartition("PlatformEvent_v1", pid), timeout=10)
    start = max(low, high - TAIL_PER_PARTITION)
    if start >= high:
        print(f"[partition {pid}] empty (low={low} high={high})")
        continue
    c.seek(TopicPartition("PlatformEvent_v1", pid, start))
    n = high - start
    got = 0
    while got < n:
        msg = c.poll(3.0)
        if msg is None:
            break
        if msg.error():
            got += 1
            continue
        try:
            val = deser(msg.value(), SerializationContext(msg.topic(), MessageField.VALUE))
        except Exception as e:
            print(f"[p{pid}@{msg.offset()}] deser fail: {e}")
            got += 1
            continue
        name = val.get("name")
        payload = val.get("payload")
        try:
            p = GenericPayloadClass.from_obj(post_json_transform(payload))
            v = p.get("value")
            vobj = json.loads(v) if isinstance(v, (str, bytes)) else v
        except Exception as e:
            vobj = f"<payload parse fail: {e}>"
        cat = vobj.get("category") if isinstance(vobj, dict) else None
        etype = vobj.get("entityType") if isinstance(vobj, dict) else None
        eurn = vobj.get("entityUrn") if isinstance(vobj, dict) else None
        op = vobj.get("operation") if isinstance(vobj, dict) else None
        print(f"[p{pid}@{msg.offset()}] name={name} entityType={etype} category={cat} operation={op} urn={eurn}")
        got += 1
c.close()
