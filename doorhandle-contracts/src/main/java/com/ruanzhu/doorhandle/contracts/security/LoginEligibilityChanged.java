package com.ruanzhu.doorhandle.contracts.security;

/** Publish inside a personnel/account-binding transaction to revoke credentials before it commits. */
public record LoginEligibilityChanged(long userId) {
    public LoginEligibilityChanged {
        if(userId<=0)throw new IllegalArgumentException("userId must be positive");
    }
}
