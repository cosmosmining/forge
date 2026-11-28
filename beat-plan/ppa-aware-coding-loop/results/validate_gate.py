#!/usr/bin/env python3
"""Gate validation: the six golden blocks must PASS, deliberately broken
candidates must FAIL, equivalent rewrites must PASS. Each test candidate is
built from the golden source by one exact text edit (checked), so the test set
is reproducible without storing third-party RTL here.
Writes results/gate_validation.json."""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "gate"))
import gate as gate_mod  # noqa: E402

ORFS = os.environ.get("ORFS_ROOT", "/opt/eda/orfs")
WORK = os.environ.get("GATE_VALIDATION_DIR", "/opt/eda/runs/gate_validation")

SPLIT_DCT_MAC = """// equivalence test only: dct_mac with the product split into two registered partial products
module dct_mac(clk, ena, dclr, din, coef, result);
	parameter dwidth = 8;
	parameter cwidth = 16;
	parameter mwidth = dwidth + cwidth;
	parameter rwidth = mwidth +3;
	input               clk;
	input               ena;
	input               dclr;
	input  [dwidth-1:0] din;
	input  [cwidth-1:0] coef;
	output [rwidth-1:0] result;
	reg [rwidth -1:0] result;
	reg signed [dwidth+8:0] pp_lo;   // din * coef[7:0] (low byte unsigned)
	reg signed [dwidth+7:0] pp_hi;   // din * coef[15:8] (signed)
	always @(posedge clk)
	  if(ena) begin
	    pp_lo <= $signed(din) * $signed({1'b0, coef[7:0]});
	    pp_hi <= $signed(din) * $signed(coef[15:8]);
	  end
	wire signed [rwidth-1:0] prod = ($signed(pp_hi) <<< 8) + $signed(pp_lo);
	always @(posedge clk)
	  if(ena)
	    if(dclr)
	      result <= prod;
	    else
	      result <= prod + result;
endmodule
"""

# name: (block, expected verdict, file to edit, old text, new text, what it checks)
TESTS = {
    "neg_arith_corner": ("dct_mac", "FAIL", "dct_mac.v", "result <= #1 ext_mult_res + result;",
                         "result <= #1 ext_mult_res + result + ((din == 8'h7f) && (coef == 16'h7fff));",
                         "arithmetic bug on a corner input (simulation should catch it)"),
    "neg_arith_rare": ("dct_mac", "FAIL", "dct_mac.v", "result <= #1 ext_mult_res + result;",
                       "result <= #1 ext_mult_res + result + ((din == 8'h5a) && (coef == 16'h1234));",
                       "arithmetic bug on one 24-bit input pair (random simulation misses it; formal must catch it)"),
    "neg_async_to_sync_reset": ("jpeg_qnr", "FAIL", "jpeg_qnr.v",
                                "always @(posedge clk or negedge rst)\n\t  if (~rst)\n\t     qnt_cnt <= #1 6'h0;",
                                "always @(posedge clk)\n\t  if (~rst)\n\t     qnt_cnt <= #1 6'h0;",
                                "asynchronous reset turned into a synchronous one"),
    "neg_initial_block": ("gcd", "FAIL", "gcd.v", "  // ctrl temporaries\n", "  initial begin end\n  // ctrl temporaries\n",
                          "an initial block (forbidden source construct)"),
    "neg_port_change": ("dct_mac", "FAIL", "dct_mac.v", "output [rwidth-1:0] result; // mac-result\n\treg [rwidth -1:0] result;",
                        "output [rwidth:0] result; // mac-result\n\treg [rwidth:0] result;", "a widened output port"),
    "neg_ifdef_trick": ("dct_mac", "FAIL", "dct_mac.v", "result <= #1 ext_mult_res + result;",
                        "`ifdef SYNTHESIS\n\t      result <= #1 ext_mult_res;\n`else\n\t      result <= #1 ext_mult_res + result;\n`endif",
                        "different code for synthesis and simulation via a new preprocessor directive"),
    "neg_latency_change": ("dct_mac", "FAIL", "dct_mac.v", "assign ext_mult_res = { {3{mult_res[mwidth-1]}}, mult_res};",
                           "reg [mwidth-1:0] mult_res2;\n\talways @(posedge clk) if(ena) mult_res2 <= mult_res;\n"
                           "\tassign ext_mult_res = { {3{mult_res2[mwidth-1]}}, mult_res2};",
                           "an extra pipeline stage (one cycle more latency)"),
    "pos_signed_multiply": ("dct_mac", "PASS", "dct_mac.v", "mult_res <= #1 icoef * idin;",
                            "mult_res <= #1 $signed(coef) * $signed(din);",
                            "equivalent rewrite of the multiplier operands"),
    "pos_split_product": ("dct_mac", "PASS", "dct_mac.v", None, SPLIT_DCT_MAC,
                          "equivalent retiming: two registered partial products instead of the product"),
}


def golden_dir(block, manifest, dst):
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for rel in manifest["blocks"][block]["golden_files"]:
        shutil.copy(os.path.join(ORFS, rel), dst)
    return dst


def main():
    manifest = json.load(open(os.path.join(ROOT, "gate", "blocks.json")))
    only = set(sys.argv[1:])
    out_path = os.path.join(HERE, "gate_validation.json")
    results = json.load(open(out_path)) if os.path.exists(out_path) else {}
    cases = [("golden_" + b, (b, "PASS", None, None, None, "unmodified original RTL"))
             for b in manifest["blocks"]] + list(TESTS.items())
    for name, (block, expect, fname, old, new, what) in cases:
        if only and name not in only:
            continue
        d = golden_dir(block, manifest, os.path.join(WORK, name, "rtl"))
        if fname:
            p = os.path.join(d, fname)
            text = open(p).read()
            if old is None:
                text = new
            else:
                if text.count(old) != 1:
                    raise SystemExit("%s: edit anchor not found exactly once" % name)
                text = text.replace(old, new)
            open(p, "w").write(text)
        rep = gate_mod.Gate(block, d, os.path.join(WORK, name, "out"), manifest).run()
        failed_at = [k for k, v in rep["checks"].items() if not v.get("ok")]
        f = rep["checks"].get("formal", {})
        results[name] = {"block": block, "checks_what": what, "expected": expect, "verdict": rep["verdict"],
                         "as_expected": rep["verdict"] == expect, "failed_at": failed_at,
                         "first_problem": ([p for c in rep["checks"].values() for p in c.get("problems", [])] or [""])[0][:300],
                         "sim_known_bits": rep["checks"].get("simulation", {}).get("known_output_bits_compared"),
                         "formal": {"dprove": f.get("dprove"), "bmc": f.get("bmc"), "strength": f.get("strength")},
                         "seconds": rep["seconds"]}
        json.dump(results, open(out_path, "w"), indent=1)
        print("%-26s expect %-4s got %-10s %s %s" % (name, expect, rep["verdict"],
                                                    "OK " if rep["verdict"] == expect else "BAD", failed_at), flush=True)


if __name__ == "__main__":
    main()
