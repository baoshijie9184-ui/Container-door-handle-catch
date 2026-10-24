package com.ruanzhu.doorhandle.common;

import java.io.IOException;
import java.nio.file.*;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import java.util.HexFormat;

/** File containment only; callers must also perform business resource authorization. */
public final class LocalFileSafety {
    private LocalFileSafety() {}
    public static Path within(Path configuredBase,Path requested) throws IOException {
        Path base=configuredBase.toAbsolutePath().normalize(), path=requested.toAbsolutePath().normalize();
        if(!path.startsWith(base)) throw new IOException("Local file outside configured root");
        for(Path cursor=path;cursor!=null && cursor.startsWith(base);cursor=cursor.getParent())
            if(Files.isSymbolicLink(cursor)) throw new IOException("Local file symlink rejected");
        Path existing=path;
        while(!Files.exists(existing,LinkOption.NOFOLLOW_LINKS)) {
            existing=existing.getParent();
            if(existing==null || !existing.startsWith(base)) throw new IOException("Local file root unavailable");
        }
        Path realBase=base.toRealPath(), realExisting=existing.toRealPath();
        if(!realExisting.startsWith(realBase)) throw new IOException("Local file canonical root changed");
        return path;
    }
    public static String reference(String resource,String kind,String relative) {
        try {
            var digest=MessageDigest.getInstance("SHA-256");
            // Fixed delimiters; none of the private location is returned as an HTTP identifier.
            return HexFormat.of().formatHex(digest.digest((resource+"\n"+kind+"\n"+relative).getBytes(StandardCharsets.UTF_8)));
        } catch(java.security.NoSuchAlgorithmException failure) { throw new IllegalStateException(failure); }
    }
}
