package com.ruanzhu.doorhandle.contracts.security;

/** No bearer credential; consume after the revocation transaction commits. */
public record LoginSessionRevoked(long userId,String sessionDigest) {}
