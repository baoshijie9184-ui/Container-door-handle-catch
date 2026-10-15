package com.ruanzhu.doorhandle.module.detection.service.report;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.detection.ReportLifecycleEvent;
import org.springframework.stereotype.Component;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

@Component
public class ReportEventCodec {
    private final ObjectMapper json;
    public ReportEventCodec(ObjectMapper json){this.json=json;}
    public ReportLifecycleEvent decode(String payload){
        try{
            if(payload==null||payload.length()>4096)throw new IllegalArgumentException();
            var node=json.readTree(payload);var fields=new HashSet<String>();node.fieldNames().forEachRemaining(fields::add);
            if(!node.isObject()||!fields.equals(Set.of("eventId","reportId","actorUserId","status","version","schemaVersion"))
                    ||!node.path("eventId").isTextual()||!node.path("reportId").isTextual()||!node.path("status").isTextual()
                    ||!node.path("actorUserId").isIntegralNumber()||!node.path("actorUserId").canConvertToLong()
                    ||!node.path("version").isIntegralNumber()||!node.path("version").canConvertToInt()
                    ||!node.path("schemaVersion").isIntegralNumber()||!node.path("schemaVersion").canConvertToInt())throw new IllegalArgumentException();
            return new ReportLifecycleEvent(node.get("eventId").textValue(),node.get("reportId").textValue(),node.get("actorUserId").longValue(),
                    node.get("status").textValue(),node.get("version").intValue(),node.get("schemaVersion").intValue());
        }catch(Exception error){throw new IllegalArgumentException("Invalid report lifecycle event");}
    }
    public String digest(ReportLifecycleEvent event){
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.writeValueAsString(event).getBytes(StandardCharsets.UTF_8)));}
        catch(Exception error){throw new IllegalStateException("Report event fingerprint unavailable");}
    }
}
