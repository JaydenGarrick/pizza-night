// Headless Ghidra script: decompile every function whose entry lies in the given address ranges and append C to an output file.
// usage (postScript args): <out.txt> <lo1-hi1> [<lo2-hi2> ...]   addresses in hex
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class ExportDecomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) { println("usage: ExportDecomp out.txt lo-hi [lo-hi ...]"); return; }
        PrintWriter out = new PrintWriter(new FileWriter(args[0], false));
        DecompInterface ifc = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        ifc.setOptions(opts);
        ifc.openProgram(currentProgram);
        AddressFactory af = currentProgram.getAddressFactory();
        FunctionManager fm = currentProgram.getFunctionManager();
        int n = 0;
        for (int i = 1; i < args.length; i++) {
            String[] parts = args[i].split("-");
            Address lo = af.getAddress(parts[0]); Address hi = af.getAddress(parts[1]);
            FunctionIterator it = fm.getFunctions(lo, true);
            while (it.hasNext()) {
                Function f = it.next();
                if (f.getEntryPoint().compareTo(hi) > 0) break;
                DecompileResults res = ifc.decompileFunction(f, 60, monitor);
                out.println("// ===== " + f.getName() + " @ " + f.getEntryPoint() + " =====");
                if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) out.println(res.getDecompiledFunction().getC());
                else out.println("// decompile failed: " + (res == null ? "null" : res.getErrorMessage()));
                n++;
                if (n % 50 == 0) println("decompiled " + n);
            }
        }
        out.close(); ifc.dispose();
        println("wrote " + n + " functions to " + args[0]);
    }
}
