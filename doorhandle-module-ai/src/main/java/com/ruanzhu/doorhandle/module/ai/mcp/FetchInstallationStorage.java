package com.ruanzhu.doorhandle.module.ai.mcp;

import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;

/** Private fixed-installation files only. Shared runtime images and legal archives are never deleted here. */
final class FetchInstallationStorage {
    private static final int MAX_ENTRIES=100000;
    private final Path root;
    FetchInstallationStorage(Path workspace){root=workspace.toAbsolutePath().normalize();}
    Path base(long owner){if(owner<1)throw new IllegalArgumentException("MCP_OWNER_INVALID");return root.resolve("users").resolve(Long.toString(owner)).resolve("mcp/fetch/installs");}
    Path directory(long owner,String id){if(id==null||!UUID.fromString(id).toString().equals(id))throw new IllegalArgumentException("MCP_INSTALLATION_INVALID");return base(owner).resolve(id);}
    record Usage(long bytes,long files){}
    Usage usage(long owner,Set<String> reserved)throws IOException {
        Path base=base(owner);FetchMcpRuntime.secure(base);if(!Files.exists(base,LinkOption.NOFOLLOW_LINKS))return new Usage(0,0);
        long[] values={0,0};
        Files.walkFileTree(base,new SimpleFileVisitor<>(){
            int visited;
            private void inspect(Path path,BasicFileAttributes attrs)throws IOException {if(++visited>MAX_ENTRIES||attrs.isOther())throw new IOException("MCP_STORAGE_UNVERIFIED");secure(attrs.isSymbolicLink()?path.getParent():path);}
            @Override public FileVisitResult preVisitDirectory(Path path,BasicFileAttributes attrs)throws IOException {inspect(path,attrs);return !path.equals(base)&&reserved.contains(base.relativize(path).getName(0).toString())?FileVisitResult.SKIP_SUBTREE:FileVisitResult.CONTINUE;}
            @Override public FileVisitResult visitFile(Path path,BasicFileAttributes attrs)throws IOException {inspect(path,attrs);if(!reserved.contains(base.relativize(path).getName(0).toString())){values[0]=Math.addExact(values[0],attrs.size());values[1]++;}return FileVisitResult.CONTINUE;}
        });
        return new Usage(values[0],values[1]);
    }
    void remove(long owner,String id)throws IOException {
        Path path=directory(owner,id);secure(path);if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS))return;
        // Scan first so an unexpected link is rejected before any known file is removed.
        var entries=new ArrayList<Path>();
        Files.walkFileTree(path,new SimpleFileVisitor<>(){
            private void inspect(Path entry,BasicFileAttributes attrs)throws IOException {
                if(entries.size()>=MAX_ENTRIES||attrs.isOther())throw new IOException("MCP_STORAGE_UNVERIFIED");
                if(attrs.isSymbolicLink()){if(!venvLibraryLink(path,entry))throw new IOException("MCP_STORAGE_UNVERIFIED");secure(entry.getParent());}
                else secure(entry);
                entries.add(entry);
            }
            @Override public FileVisitResult preVisitDirectory(Path entry,BasicFileAttributes attrs)throws IOException {inspect(entry,attrs);return FileVisitResult.CONTINUE;}
            @Override public FileVisitResult visitFile(Path entry,BasicFileAttributes attrs)throws IOException {inspect(entry,attrs);return FileVisitResult.CONTINUE;}
        });
        entries.sort(Comparator.comparingInt(Path::getNameCount).reversed());
        for(Path entry:entries){
            if(Files.isSymbolicLink(entry)){secure(entry.getParent());if(!venvLibraryLink(path,entry))throw new IOException("MCP_STORAGE_UNVERIFIED");}
            else secure(entry);
            Files.deleteIfExists(entry); // Deletes the link itself; never walks its target.
        }
        if(Files.exists(path,LinkOption.NOFOLLOW_LINKS))throw new IOException("MCP_STORAGE_DELETE_UNVERIFIED");
    }
    private static boolean venvLibraryLink(Path installation,Path entry)throws IOException {
        // CPython venv creates lib64 -> lib even when the Python executable is copied.
        return entry.equals(installation.resolve(".venv/lib64"))&&Files.readSymbolicLink(entry).equals(Path.of("lib"));
    }
    private static void secure(Path path)throws IOException {try{FetchMcpRuntime.secure(path);}catch(Exception error){throw new IOException("MCP_STORAGE_UNVERIFIED",error);}}
}
