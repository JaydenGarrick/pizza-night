// Headless: for each hex address listed (one per line) in args[1], create a function there if missing and append its decompiled C to args[0].
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;

public class ExportFuncs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        List<String> lines = Files.readAllLines(Paths.get(args[1]));
        PrintWriter out = new PrintWriter(new FileWriter(args[0], false));
        DecompInterface ifc = new DecompInterface(); ifc.setOptions(new DecompileOptions()); ifc.openProgram(currentProgram);
        AddressFactory af = currentProgram.getAddressFactory(); FunctionManager fm = currentProgram.getFunctionManager();
        int n = 0;
        for (String line : lines) {
            line = line.trim(); if (line.isEmpty()) continue;
            Address a = af.getAddress(line);
            Function f = fm.getFunctionAt(a);
            if (f == null) { CreateFunctionCmd cmd = new CreateFunctionCmd(a); cmd.applyTo(currentProgram, monitor); f = fm.getFunctionAt(a); }
            out.println("// ===== " + (f == null ? "nofunc" : f.getName()) + " @ " + line + " =====");
            if (f == null) { out.println("// could not create function"); continue; }
            DecompileResults res = ifc.decompileFunction(f, 60, monitor);
            if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) out.println(res.getDecompiledFunction().getC());
            else out.println("// decompile failed: " + (res == null ? "null" : res.getErrorMessage()));
            n++;
        }
        out.close(); ifc.dispose(); println("wrote " + n + " functions");
    }
}
