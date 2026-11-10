package com.ruanzhu.doorhandle.module.system.dto;

import lombok.Data;

@Data
public class LoginResponse {
    @com.fasterxml.jackson.databind.annotation.JsonSerialize(using=com.fasterxml.jackson.databind.ser.std.ToStringSerializer.class)
    private Long userId;
    private String token;
    private String refreshToken;
    private String username;
    private String email;
    private String phone;
    private String realName;
    private String role;
    private String accountContext;
    @com.fasterxml.jackson.annotation.JsonIgnore
    private java.time.Instant accessExpiresAt;
    @com.fasterxml.jackson.annotation.JsonIgnore
    private java.time.Instant refreshExpiresAt;
} 
