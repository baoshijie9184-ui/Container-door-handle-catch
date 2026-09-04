package com.ruanzhu.doorhandlecatch.dto;

import lombok.Data;

@Data
public class LoginResponse {
    private Long userId;
    private String token;
    private String refreshToken;
    private String username;
    private String email;
    private String phone;
    private String realName;
} 
