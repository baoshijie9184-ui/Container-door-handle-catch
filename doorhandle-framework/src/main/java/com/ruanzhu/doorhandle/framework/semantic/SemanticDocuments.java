package com.ruanzhu.doorhandle.framework.semantic;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

public final class SemanticDocuments {
    private SemanticDocuments() { }
    /** Same SHA-256 based UUID protocol in Java and the Mem0 adapter; public IDs stay unchanged. */
    public static UUID pointId(String collection,String logicalId) {
        if(logicalId==null||logicalId.isBlank()||logicalId.length()>512||logicalId.chars().anyMatch(Character::isISOControl))throw new IllegalArgumentException("Invalid vector logical identity");
        try {
            byte[] bytes=Arrays.copyOf(MessageDigest.getInstance("SHA-256").digest(
                    ("doorhandle-vector-sha256-v8-v1\0"+collection+"\0"+logicalId).getBytes(StandardCharsets.UTF_8)),16);
            bytes[6]=(byte)((bytes[6]&0x0f)|0x80);bytes[8]=(byte)((bytes[8]&0x3f)|0x80);
            var buffer=ByteBuffer.wrap(bytes);return new UUID(buffer.getLong(),buffer.getLong());
        } catch(java.security.NoSuchAlgorithmException unavailable) {throw new IllegalStateException(unavailable);}
    }
    /** Lossless Unicode/code-point split before the provider's UTF-8 byte limit; no truncation. */
    public static List<String> split(String text) {
        if(text==null||text.isBlank())throw new IllegalArgumentException("Semantic text is required");
        var parts=new ArrayList<String>();var part=new StringBuilder();int bytes=0;
        for(int offset=0;offset<text.length();) {
            int cp=text.codePointAt(offset);String value=new String(Character.toChars(cp));int size=value.getBytes(StandardCharsets.UTF_8).length;
            if(bytes+size>7800){parts.add(part.toString());part.setLength(0);bytes=0;}
            part.append(value);bytes+=size;offset+=Character.charCount(cp);
        }
        if(!part.isEmpty())parts.add(part.toString());return List.copyOf(parts);
    }
}
