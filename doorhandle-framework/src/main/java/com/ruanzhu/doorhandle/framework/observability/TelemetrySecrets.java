package com.ruanzhu.doorhandle.framework.observability;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/** 只读运行时 secret 文件，错误不携带路径、文件内容或原异常。 */
public final class TelemetrySecrets {
    private TelemetrySecrets(){}
    public static String read(String file) {
        try {
            if(file==null||file.isBlank())throw new IllegalArgumentException();
            Path path=Path.of(file);
            if(!Files.isRegularFile(path)||Files.size(path)>4096)throw new IllegalArgumentException();
            String value=Files.readString(path,StandardCharsets.UTF_8).strip();
            if(value.length()<16||value.length()>2048||value.chars().anyMatch(c->c<33||c>126))throw new IllegalArgumentException();
            return value;
        } catch(Exception ignored){throw new IllegalStateException("TELEMETRY_SECRET_INVALID");}
    }
}
