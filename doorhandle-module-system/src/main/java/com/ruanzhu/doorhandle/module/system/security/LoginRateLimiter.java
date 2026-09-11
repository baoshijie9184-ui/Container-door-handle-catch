package com.ruanzhu.doorhandle.module.system.security;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 登录速率限制器
 * 基于内存的简单实现，限制每个 IP 每分钟的登录尝试次数
 */
@Component
@Slf4j
public class LoginRateLimiter {

    // 最大尝试次数
    private static final int MAX_ATTEMPTS = 5;
    // 时间窗口（毫秒）- 1分钟
    private static final long WINDOW_MS = 60 * 1000;

    // IP -> 尝试记录
    private final ConcurrentHashMap<String, AttemptRecord> attempts = new ConcurrentHashMap<>();

    /**
     * 检查是否允许登录尝试
     * @param ip 客户端 IP
     * @return true 如果允许尝试，false 如果已超过限制
     */
    public boolean isAllowed(String ip) {
        cleanupExpired();

        AttemptRecord record = attempts.compute(ip, (key, existing) -> {
            if (existing == null || existing.isExpired()) {
                return new AttemptRecord();
            }
            return existing;
        });

        return record.getCount() < MAX_ATTEMPTS;
    }

    /**
     * 记录一次失败的登录尝试
     * @param ip 客户端 IP
     */
    public void recordFailedAttempt(String ip) {
        attempts.compute(ip, (key, existing) -> {
            if (existing == null || existing.isExpired()) {
                AttemptRecord newRecord = new AttemptRecord();
                newRecord.increment();
                return newRecord;
            }
            existing.increment();
            return existing;
        });

        log.warn("登录失败尝试 - IP: {}, 当前尝试次数: {}", ip, attempts.get(ip).getCount());
    }

    /**
     * 登录成功后清除该 IP 的记录
     * @param ip 客户端 IP
     */
    public void recordSuccess(String ip) {
        attempts.remove(ip);
    }

    /**
     * 获取剩余等待时间（秒）
     * @param ip 客户端 IP
     * @return 剩余等待时间，如果不需要等待则返回 0
     */
    public long getRemainingWaitSeconds(String ip) {
        AttemptRecord record = attempts.get(ip);
        if (record == null || record.isExpired() || record.getCount() < MAX_ATTEMPTS) {
            return 0;
        }
        return record.getRemainingMs() / 1000;
    }

    /**
     * 清理过期的记录
     */
    private void cleanupExpired() {
        attempts.entrySet().removeIf(entry -> entry.getValue().isExpired());
    }

    /**
     * 尝试记录内部类
     */
    private static class AttemptRecord {
        private final AtomicInteger count = new AtomicInteger(0);
        private final long createdAt = System.currentTimeMillis();

        void increment() {
            count.incrementAndGet();
        }

        int getCount() {
            return count.get();
        }

        boolean isExpired() {
            return System.currentTimeMillis() - createdAt > WINDOW_MS;
        }

        long getRemainingMs() {
            long elapsed = System.currentTimeMillis() - createdAt;
            return Math.max(0, WINDOW_MS - elapsed);
        }
    }
}
