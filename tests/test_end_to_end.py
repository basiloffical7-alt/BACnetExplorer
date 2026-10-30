"""End-to-end test: BACnetClient against the simulator over real UDP sockets."""
import os, sys, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bacnet import constants as C, codec as X
from bacnet.client import BACnetClient, BACnetError
from bacnet.codec import ObjectId, Real, Address

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sim = subprocess.Popen([sys.executable, "bacnet_simulator.py", "--port", "47809",
                        "--routed", "2", "--big", "300", "--no-equipment"], cwd=root,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.0)
logs = []
cl = BACnetClient("127.0.0.1", 47820, "127.255.255.255", timeout=2.0, retries=1)
cl.on_log = lambda lvl, m: logs.append((lvl, m))
devs = []
cl.on_device = lambda d, new: devs.append(d.instance) if new else None
updates = []
cl.on_subscription = lambda s: updates.append((s.sub_id, s.value))
try:
    cl.start()
    cl.who_is(target=("127.0.0.1", 47809))
    time.sleep(1.0)
    print("discovered:", sorted(devs), {i: str(cl.devices[i].address) for i in devs})
    assert sorted(devs) == [1001, 1002, 1003]
    main = cl.devices[1001]; vav = cl.devices[1002]
    assert vav.address.net == 2001 and vav.address.mac == bytes([10])

    cl.read_device_info(main); print("device:", main.name, main.vendor_name, main.model_name, "rpm", main.supports_rpm)
    objs = cl.read_object_list(main)            # segmented response (~300 objects)
    print("objects:", len(objs)); assert len(objs) == 300 + 14
    names = cl.read_object_names(main, objs); print("names:", len(names), names[ObjectId(0,1)])
    assert len(names) == len(objs)

    props = cl.read_all_properties(main, ObjectId(2, 1))
    for pr in props:
        print("   ", C.property_name(pr.prop).ljust(22), X.format_value(pr.value, 2, pr.prop) if pr.error is None else pr.error)
    # routed device
    cl.read_device_info(vav); print("routed:", vav.name)
    vobjs = cl.read_object_list(vav); print("routed objects:", len(vobjs))

    # write with priority, read back PV and priority array
    av = ObjectId(2, 1)
    cl.write_property(main.address, av, 85, Real(19.5), priority=8)
    pv = cl.read_property(main.address, av, 85); print("PV after write:", pv); assert abs(pv - 19.5) < 1e-6
    pa = cl.read_property(main.address, av, 87); print("PA:", X.format_value(pa, 2, 87))
    print("PA[8]:", cl.read_property(main.address, av, 87, 8))
    cl.write_property(main.address, av, 85, X.NULL, priority=8)
    print("PV after relinquish:", cl.read_property(main.address, av, 85))
    # binary write
    cl.write_property(main.address, ObjectId(4, 1), 85, X.Enumerated(1), priority=8)
    print("BO PV:", X.format_value(cl.read_property(main.address, ObjectId(4,1), 85), 4, 85))
    # errors
    try:
        cl.read_property(main.address, ObjectId(0, 99), 85); raise SystemExit("expected error")
    except BACnetError as e: print("expected error:", e)
    try:
        cl.write_property(main.address, ObjectId(0, 1), 85, Real(1.0)); raise SystemExit("expected error")
    except BACnetError as e: print("expected error:", e)

    # COV (unconfirmed + confirmed) + routed + polling
    s1 = cl.add_subscription(main, ObjectId(0, 1), confirmed=False, lifetime=60)
    s2 = cl.add_subscription(vav, ObjectId(2, 1), confirmed=True, lifetime=60)
    s3 = cl.add_subscription(main, ObjectId(0, 3), force_poll=True, poll_interval=1)
    time.sleep(0.5)
    cl.write_property(vav.address, ObjectId(2, 1), 85, Real(21.0), priority=10)
    time.sleep(4)
    for s in (s1, s2, s3):
        print(f"sub {s.sub_id} {s.object_id} mode={s.mode} state={s.state} value={s.value} flags={s.status_flags} history={len(s.history)}")
        assert s.value is not None
    assert abs(s2.value - 21.0) < 1e-6
    # manual add with wildcard instance
    d = cl.add_device_manual("127.0.0.1", 47809); print("manual add ->", d.instance)
    cl.time_sync(main.address)
    for sid in list(cl.subscriptions): cl.remove_subscription(sid)
    errs = [m for l, m in logs if l == "error"]
    print("client errors:", errs); assert not errs
    print("ALL TESTS PASSED")
finally:
    cl.stop(); sim.terminate()
    out = sim.communicate(timeout=3)[0]
    print("--- simulator output ---\n" + out)
