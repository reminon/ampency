// FindRndDecrypt.java - Find RND file decryption in Amplitude PS2 executable
// @category PS2Analysis

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.util.*;

public class FindRndDecrypt extends GhidraScript {
    @Override
    public void run() throws Exception {
        PrintWriter out = new PrintWriter(new FileWriter("/tmp/rnd_analysis.txt"));
        
        out.println("=== FindRndDecrypt ===");
        
        Memory mem = currentProgram.getMemory();
        FunctionManager fm = currentProgram.getFunctionManager();
        ReferenceManager rm = currentProgram.getReferenceManager();
        
        out.println("Total functions: " + fm.getFunctionCount());
        
        // Search for magic 0xCCBEDEAF (little-endian: AF DE BE CC)
        byte[] magic = {(byte)0xAF, (byte)0xDE, (byte)0xBE, (byte)0xCC};
        Address found = mem.findBytes(mem.getMinAddress(), magic, null, true, monitor);
        if (found != null) {
            out.println("Magic found at: " + found);
            for (Reference ref : rm.getReferencesTo(found)) {
                out.println("  Ref from: " + ref.getFromAddress());
                Function f = fm.getFunctionContaining(ref.getFromAddress());
                if (f != null) out.println("  In func: " + f.getEntryPoint());
            }
        } else {
            out.println("Magic not found");
        }
        
        // Search for tunnel_new.rnd string
        byte[] rndStr = "tunnel_new.rnd".getBytes();
        Address rndAddr = mem.findBytes(mem.getMinAddress(), rndStr, null, true, monitor);
        if (rndAddr != null) {
            out.println("tunnel_new.rnd at: " + rndAddr);
            for (Reference ref : rm.getReferencesTo(rndAddr)) {
                out.println("  Ref from: " + ref.getFromAddress());
                Function f = fm.getFunctionContaining(ref.getFromAddress());
                if (f != null) out.println("  In func: " + f.getEntryPoint());
            }
        } else {
            out.println("tunnel_new.rnd not found");
        }

        // Search for RndLoader string
        byte[] rndLoader = "RndLoader".getBytes();
        Address rlAddr = mem.findBytes(mem.getMinAddress(), rndLoader, null, true, monitor);
        if (rlAddr != null) {
            out.println("RndLoader at: " + rlAddr);
        }
        
        out.println("Done.");
        out.close();
    }
}
