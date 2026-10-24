package com.ruanzhu.doorhandle.module.infra.security;

import com.ruanzhu.doorhandle.common.LocalFileSafety;
import com.ruanzhu.doorhandle.contracts.files.BusinessFileGrant;
import org.springframework.core.io.FileSystemResource;
import org.springframework.security.access.AccessDeniedException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.Objects;
import java.util.function.Supplier;

/** Immutable response metadata, reauthorized immediately before opening bytes. Not a browser JSON DTO. */
public final class AuthorizedLocalFileResource extends FileSystemResource {
    private final Path base,path;
    private final BusinessFileGrant grant;
    private final Supplier<BusinessFileGrant> reauthorize;
    private final BasicFileAttributes snapshot;
    public AuthorizedLocalFileResource(Path base,Path path,BusinessFileGrant grant,Supplier<BusinessFileGrant> reauthorize)throws IOException {
        super(path);this.base=base;this.path=LocalFileSafety.within(base,path);this.grant=Objects.requireNonNull(grant);this.reauthorize=reauthorize;
        snapshot=Files.readAttributes(this.path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        if(!snapshot.isRegularFile()) throw new IOException("Not a regular business file");
    }
    public String getId() { return grant.resourceId(); }
    public String getFileId() { return grant.fileId(); }
    public Long getVersion() { return grant.version(); }
    @Override public long contentLength() { return snapshot.size(); }
    @Override public InputStream getInputStream()throws IOException {
        if(!grant.equals(reauthorize.get())) throw new AccessDeniedException("文件所属资源或访问权限已变化");
        try {
            LocalFileSafety.within(base,path);
            var current=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
            if(!current.isRegularFile() || !Objects.equals(snapshot.fileKey(),current.fileKey())
                    || snapshot.size()!=current.size() || !snapshot.lastModifiedTime().equals(current.lastModifiedTime()))
                throw new IOException("Business file changed before streaming");
            return Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS);
        } catch(IOException unavailable) {
            // Filesystem exceptions contain physical paths. Do not forward them to an HTTP error body.
            throw new IOException("Business file cannot be opened or has changed");
        }
    }
    @Override public java.nio.channels.ReadableByteChannel readableChannel()throws IOException {
        return java.nio.channels.Channels.newChannel(getInputStream());
    }
}
