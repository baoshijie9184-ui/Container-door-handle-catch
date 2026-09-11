package com.ruanzhu.doorhandle.module.system.security;

public record TenantContext(Long userId, String username) {
    public TenantContext {
        if (userId == null || userId <= 0) throw new IllegalArgumentException("userId must be positive");
        if (username == null || username.isBlank()) throw new IllegalArgumentException("username is required");
    }

    public String mem0UserId() {
        return "doorhandlecatch:user:" + userId;
    }
}
