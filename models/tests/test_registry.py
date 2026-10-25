"""Registry tests: the real catalog + variants validate, production task
selections resolve exactly as before the registry split (golden), and each
class of registry error is caught. Run from the repo root:
  <venv>/bin/python3 -m unittest discover -s models/tests -v
(needs pyyaml + jsonschema, as scripts/validate-model-catalog)."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import registry  # noqa: E402

# Task selections and their serving path as deployed on 2026-10-25, before the
# catalog/variants split: (model/variant, slot, profile, MLServer model).
GOLDEN = {
    ("prompt-free-segmentation", "default"): ("yoloe-v8s-pf/tpu-fp16r-gpu-head-fp16acc32", "hetero1", "yoloe-v8s-fast", "yoloe-v8s-pf"),
    ("prompt-free-segmentation", "fallback"): ("yoloe-v8s-pf/gpu-fp32", "hetero1", "yoloe-v8s-default", None),
    ("box-refinement", "default"): ("edgesam-3x/tpu-fp16r-gpu-neck-fp32", "hetero2", "edgesam3x-fast", "edgesam3x-box"),
    ("box-refinement", "fallback"): ("edgesam-3x/gpu-fp32", "hetero2", "edgesam3x-default", None),
    ("box-refinement", "quality"): ("sam2.1-hiera-tiny/gpu-fp32", None, None, None),
}


class RealRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = registry.Registry.load()

    def test_validates(self):
        self.assertEqual(self.reg.validate(), [])

    def test_production_resolution_unchanged(self):
        for (task, sel), (ref, slot, profile, ml) in GOLDEN.items():
            got = self.reg.resolve(f"{task}@{sel}")
            self.assertEqual(got, ref, f"{task}@{sel}")
            if slot is None:   # not a production selection: the variant is pinned, its staging may change
                self.assertNotEqual(self.reg.variant(got)["status"], "production", f"{task}@{sel}")
                continue
            s = self.reg.serving_of(got) or {}
            self.assertEqual((s.get("slot"), s.get("profile"), s.get("mlserver_model")), (slot, profile, ml), f"{task}@{sel}")
            self.assertEqual(self.reg.variant(got)["status"], "production", f"{task}@{sel}")

    def test_available_tasks(self):
        avail = {t for t in self.reg.tasks if self.reg.task_available(t)}
        self.assertEqual(avail, {"prompt-free-segmentation", "box-refinement"})

    def test_previous_ids_resolve(self):
        self.assertEqual(self.reg.resolve("edgesam3x/tpu-fp16r-gpu-neck-fp32"), "edgesam-3x/tpu-fp16r-gpu-neck-fp32")
        self.assertEqual(self.reg.resolve("edgesam3x@fast"), "edgesam-3x/tpu-fp16r-gpu-neck-fp32")
        self.assertEqual(self.reg.resolve("yoloe-v8s-pf/gpu-mixed"), "yoloe-v8s-pf/gpu-fp16acc32")

    def test_model_aliases(self):
        self.assertEqual(self.reg.resolve("yoloe-v8s-pf"), "yoloe-v8s-pf/gpu-fp32")
        self.assertEqual(self.reg.resolve("yoloe-v8s-pf@fast"), "yoloe-v8s-pf/tpu-fp16r-gpu-head-fp16acc32")
        self.assertEqual(self.reg.resolve("efficientsam3-rvm@fast"), "efficientsam3-rvm/gpu-trunk-fp32-neck-fp16acc32-grounding-fp16acc32")

    def test_blocked_default_alias_vs_servable_task_default(self):
        # EfficientSAM3: the model's validated default (FP32) can't be served on
        # the Pixel 6 and stays the reference; the task's default is the fast
        # configuration, which can. A task's quality may name the blocked one.
        model_default = self.reg.resolve("efficientsam3-rvm")
        self.assertTrue(self.reg.variant(model_default).get("serving_blocked"))
        task_default = self.reg.resolve("text-prompted-segmentation@default")
        self.assertFalse(self.reg.variant(task_default).get("serving_blocked"))
        self.assertIsNotNone(self.reg.serving_of(task_default))
        self.assertEqual(self.reg.resolve("text-prompted-segmentation@quality"), model_default)

    def test_blocked_variants_have_no_serving(self):
        for ref, v in self.reg.variants["variants"].items():
            if v.get("serving_blocked"):
                self.assertNotIn(v["status"], registry.SERVED, ref)
                self.assertNotIn("serving", v, ref)

    def test_validated_models_are_not_endpoints(self):
        for name, ref, status in self.reg.endpoints():
            self.assertIn(status, registry.SERVED)
            self.assertNotEqual(self.reg.variant(ref)["status"], "validated")

    def test_every_variant_has_known_measure_kinds(self):
        kinds = {b["measure"] for v in self.reg.variants["variants"].values() for b in v.get("benchmarks") or []}
        self.assertTrue(kinds <= {"device", "worker", "round-trip", "summed", "connected"})


class Mutations(unittest.TestCase):
    """Each breaks one rule in a copy of the real registry; validate() must say so."""

    def setUp(self):
        base = registry.Registry.load()
        self.catalog, self.variants = base.catalog, base.variants

    def errors(self, mutate):
        cat, var = copy.deepcopy(self.catalog), copy.deepcopy(self.variants)
        mutate(cat, var)
        return registry.Registry(cat, var).validate()

    def assertCaught(self, mutate, fragment):
        errs = self.errors(mutate)
        self.assertTrue(any(fragment in e for e in errs), f"expected an error containing {fragment!r}, got {errs}")

    def test_duplicate_model_id(self):
        def m(c, v):
            c["models"]["mi-gan-512"]["previous_ids"] = ["edgesam3x"]
        self.assertCaught(m, "model id edgesam3x used by both")

    def test_duplicate_variant_id(self):
        def m(c, v):
            v["variants"]["mi-gan-512/gpu-fp16"]["previous_ids"] = ["gpu-fp32"]
        self.assertCaught(m, "variant id mi-gan-512/gpu-fp32 used by both")

    def test_variant_of_unknown_model(self):
        def m(c, v):
            v["variants"]["nonexistent/gpu-fp32"] = copy.deepcopy(v["variants"]["mi-gan-512/gpu-fp32"])
        self.assertCaught(m, "no model nonexistent")

    def test_alias_to_unknown_variant(self):
        def m(c, v):
            c["models"]["mi-gan-512"]["aliases"]["fast"] = "gpu-int4"
        self.assertCaught(m, "alias fast -> unknown variant gpu-int4")

    def test_alias_to_rejected_variant(self):
        def m(c, v):
            c["models"]["dinov2-s14"]["aliases"]["fast"] = "gpu-fp16acc32"
        self.assertCaught(m, "which is rejected")

    def test_alias_to_internal_variant(self):
        def m(c, v):
            c["models"]["yoloe-v8s-pf"]["aliases"]["fallback"] = "gpu-fp16acc32"
        self.assertCaught(m, "not selectable")

    def test_bad_alias_name(self):
        def m(c, v):
            c["models"]["mi-gan-512"]["aliases"]["turbo"] = "gpu-fp16"
        self.assertCaught(m, "catalog: models.mi-gan-512.aliases")

    def test_unresolved_task_selection(self):
        def m(c, v):
            c["tasks"]["inpainting"]["default"] = "mi-gan-512/gpu-int4"
        self.assertCaught(m, "tasks.inpainting.default")

    def test_available_task_selecting_unserved_variant(self):
        def m(c, v):
            c["tasks"]["inpainting"]["available"] = True
        self.assertCaught(m, "advertised as available")

    def test_task_selecting_rejected_variant(self):
        def m(c, v):
            c["tasks"]["image-embedding"]["default"] = "dinov2-s14/gpu-fp16acc32"
        self.assertCaught(m, "is rejected")

    def test_stage_with_unknown_artifact(self):
        def m(c, v):
            v["variants"]["mi-gan-512/gpu-fp32"]["stages"][0]["artifact"] = "tflite_npu"
        self.assertCaught(m, "unknown artifact tflite_npu")

    def test_artifact_without_hashes(self):
        def m(c, v):
            del c["models"]["mi-gan-512"]["artifacts"]["tflite_gpu"]["files"]
        self.assertCaught(m, "has no files")

    def test_duplicate_device_file_name(self):
        def m(c, v):
            c["models"]["mi-gan-512"]["artifacts"]["tflite_gpu"]["files"][0]["name"] = "dinov2_s_fp16.tflite"
        self.assertCaught(m, "device names must be unique")

    def test_missing_record(self):
        def m(c, v):
            v["variants"]["mi-gan-512/gpu-fp32"]["validation"]["record"] = "experiments/pixel6/results.md#no-such-heading"
        self.assertCaught(m, "no heading with that anchor")

    def test_missing_record_file(self):
        def m(c, v):
            v["variants"]["mi-gan-512/gpu-fp32"]["benchmarks"][0]["record"] = "experiments/nowhere.md"
        self.assertCaught(m, "file not found")

    def test_served_variant_without_profile(self):
        def m(c, v):
            v["variants"]["yoloe-v8s-pf/gpu-fp32"]["serving"].pop("profile")
        self.assertCaught(m, "needs serving.profile")

    def test_served_variant_with_unknown_profile(self):
        def m(c, v):
            v["variants"]["yoloe-v8s-pf/gpu-fp32"]["serving"]["profile"] = "yoloe-v8s-turbo"
        self.assertCaught(m, "supervisor profile yoloe-v8s-turbo not defined")

    def test_served_variant_profile_in_wrong_slot(self):
        def m(c, v):
            v["variants"]["yoloe-v8s-pf/gpu-fp32"]["serving"]["slot"] = "hetero2"
        self.assertCaught(m, "belongs to slot hetero1")

    def test_worker_config_with_foreign_artifact(self):
        def m(c, v):
            v["variants"]["edgesam-3x/gpu-fp32"]["serving"]["worker_config"] = "hosts/cerebrate-pixel6/cerebrate-hetero/configs/yoloe-v8s-default.conf"
        self.assertCaught(m, "not this variant's artifacts")

    def test_endpoint_profile_mismatch(self):
        def m(c, v):
            v["variants"]["yoloe-v8s-pf/gpu-fp32"]["serving"]["mlserver_model"] = "yoloe-v8s-pf"
        self.assertCaught(m, "serves profile yoloe-v8s-fast, not yoloe-v8s-default")

    def test_rejected_variant_cannot_serve(self):
        def m(c, v):
            v["variants"]["dinov2-s14/gpu-fp16acc32"]["serving"] = {"slot": "hetero1"}
        self.assertCaught(m, "status rejected can't carry serving")

    def test_task_default_cannot_select_blocked_variant(self):
        def m(c, v):
            c["tasks"]["text-prompted-segmentation"]["default"] = "efficientsam3-rvm/gpu-fp32"
        self.assertCaught(m, "a task's default and fallback must be servable")

    def test_blocked_variant_cannot_be_staged(self):
        def m(c, v):
            v["variants"]["sam2.1-hiera-tiny/gpu-fp16acc32"]["status"] = "staged"
            v["variants"]["sam2.1-hiera-tiny/gpu-fp16acc32"]["serving"] = {"slot": "gpu-sam2", "profile": "sam2.1-hiera-tiny-default"}
        self.assertCaught(m, "serving_blocked (unresolved")

    def test_variants_in_catalog_rejected(self):
        def m(c, v):
            c["models"]["mi-gan-512"]["variants"] = {}
        self.assertCaught(m, "Additional properties")


if __name__ == "__main__":
    unittest.main()
