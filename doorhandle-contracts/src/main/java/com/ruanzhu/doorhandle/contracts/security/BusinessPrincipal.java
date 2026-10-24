package com.ruanzhu.doorhandle.contracts.security;

/** Server-issued authenticated identity. Display names alone must never establish account ownership. */
public interface BusinessPrincipal {
    Long userId();
    String username();
}
