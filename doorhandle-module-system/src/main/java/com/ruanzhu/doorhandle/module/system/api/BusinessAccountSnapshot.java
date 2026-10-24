package com.ruanzhu.doorhandle.module.system.api;

import com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi.Account;
import com.ruanzhu.doorhandle.module.system.entity.User;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;

/** Selection metadata only; never hashes or returns passwords, contact details or credentials. */
final class BusinessAccountSnapshot {
    private BusinessAccountSnapshot() {}

    static Account describe(User user) {
        String role = user.getRole() == null ? "" : user.getRole().toUpperCase(Locale.ROOT);
        if (user.getId() == null || user.getId() < 1 || user.getUsername() == null || user.getUsername().isBlank() || user.getUsername().length() > 64
                || !Set.of("ADMIN", "SUPERVISOR", "INSPECTOR", "OPERATOR").contains(role)) {
            throw new IllegalArgumentException("业务账号已失效");
        }
        try {
            var digest = MessageDigest.getInstance("SHA-256");
            for (String value : List.of(user.getId().toString(), user.getUsername(), role,
                    Objects.toString(user.getCreatedAt(), ""), Objects.toString(user.getUpdatedAt(), ""))) {
                byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
                digest.update(ByteBuffer.allocate(4).putInt(bytes.length).array());
                digest.update(bytes);
            }
            return new Account(user.getId(), user.getUsername(), role, HexFormat.of().formatHex(digest.digest()));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
