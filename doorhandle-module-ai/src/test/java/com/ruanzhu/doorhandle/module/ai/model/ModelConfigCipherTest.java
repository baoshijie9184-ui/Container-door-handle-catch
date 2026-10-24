package com.ruanzhu.doorhandle.module.ai.model;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import java.util.Base64;
import static org.assertj.core.api.Assertions.*;

class ModelConfigCipherTest {
    @TempDir Path directory;

    @Test void uniqueNoncesAndAuthenticatedPurposeVersionAndKey() {
        var cipher = new ModelConfigCipher(new byte[32]);
        String first=cipher.seal("model-config",7,"fixture-private-key");
        String second=cipher.seal("model-config",7,"fixture-private-key");
        assertThat(first).isNotEqualTo(second).doesNotContain("fixture-private-key");
        assertThat(cipher.open("model-config",7,first)).isEqualTo("fixture-private-key");
        assertThatThrownBy(()->cipher.open("mem0-llm",7,first)).hasMessage("模型配置完整性校验失败");
        assertThatThrownBy(()->cipher.open("model-config",8,first)).hasMessage("模型配置完整性校验失败");
        var another=new byte[32];another[0]=1;
        assertThatThrownBy(()->new ModelConfigCipher(another).open("model-config",7,first)).hasMessage("模型配置完整性校验失败");
        String[] parts=first.split("\\.");byte[] bytes=Base64.getDecoder().decode(parts[2]);bytes[0]^=1;
        assertThatThrownBy(()->cipher.open("model-config",7,parts[0]+"."+parts[1]+"."+Base64.getEncoder().encodeToString(bytes)))
                .hasMessage("模型配置完整性校验失败");
    }

    @Test void externalSecretMustExistAndHaveExactly256Bits() throws Exception {
        assertThatThrownBy(()->new ModelConfigCipher(directory.resolve("absent"))).hasMessage("无法读取模型主密钥 Secret 文件");
        Path file=directory.resolve("master.key");Files.writeString(file,Base64.getEncoder().encodeToString(new byte[32]));
        assertThat(new ModelConfigCipher(file).open("test",1,new ModelConfigCipher(file).seal("test",1,"ok"))).isEqualTo("ok");
        assertThatThrownBy(()->new ModelConfigCipher(new byte[16])).isInstanceOf(IllegalArgumentException.class);
    }
}
