package com.ruanzhu.doorhandle.contracts.security;

import java.time.Instant;

/** Current server-side session and account facts; never returns a bearer credential. */
public interface LoginSessionAccess {
    record Session(long userId,String username,String role,String sessionDigest,String accountContext,Instant expiresAt) {}
    Session requireActive(long userId,String username,String sessionDigest);
}
