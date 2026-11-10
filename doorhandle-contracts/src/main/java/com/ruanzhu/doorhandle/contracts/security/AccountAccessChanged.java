package com.ruanzhu.doorhandle.contracts.security;

/** Account permissions changed; consumers must re-read authorization after commit. */
public record AccountAccessChanged(long userId) {}
