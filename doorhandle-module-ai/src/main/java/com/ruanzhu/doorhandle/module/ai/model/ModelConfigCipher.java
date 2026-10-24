package com.ruanzhu.doorhandle.module.ai.model;

import javax.crypto.Cipher;
import javax.crypto.spec.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.*;

/** Versioned authenticated encryption. The external master key never enters the database. */
public final class ModelConfigCipher {
    private final byte[] key;private final SecureRandom random=new SecureRandom();
    public ModelConfigCipher(Path file){this(read(file));}
    public ModelConfigCipher(byte[] value){if(value==null||value.length!=32)throw new IllegalArgumentException("模型主密钥必须是 256 位");key=value.clone();}
    private static byte[] read(Path file){try{if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||Files.size(file)>128)throw new IllegalArgumentException();return Base64.getDecoder().decode(Files.readString(file).trim());}catch(Exception error){throw new IllegalStateException("无法读取模型主密钥 Secret 文件");}}
    public String seal(String purpose,long revision,String plaintext){try{byte[] nonce=new byte[12];random.nextBytes(nonce);var cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(key,"AES"),new GCMParameterSpec(128,nonce));cipher.updateAAD(aad(purpose,revision));return "v1."+Base64.getEncoder().encodeToString(nonce)+"."+Base64.getEncoder().encodeToString(cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException("模型配置加密失败");}}
    public String open(String purpose,long revision,String envelope){try{String[] parts=envelope.split("\\.",-1);if(parts.length!=3||!parts[0].equals("v1"))throw new IllegalArgumentException();byte[] nonce=Base64.getDecoder().decode(parts[1]);if(nonce.length!=12)throw new IllegalArgumentException();var cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,new SecretKeySpec(key,"AES"),new GCMParameterSpec(128,nonce));cipher.updateAAD(aad(purpose,revision));return new String(cipher.doFinal(Base64.getDecoder().decode(parts[2])),StandardCharsets.UTF_8);}catch(Exception error){throw new IllegalStateException("模型配置完整性校验失败");}}
    private byte[] aad(String purpose,long revision){return ("doorhandle:"+purpose+":"+revision).getBytes(StandardCharsets.UTF_8);}
}
