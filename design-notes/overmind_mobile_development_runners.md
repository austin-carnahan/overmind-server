# Overmind — Mobile Development Runners and Agent Execution Workflow

## Status

Future development workflow / infrastructure design note.

## Purpose

Overmind should support autonomous and semi-autonomous mobile software development across Flutter and React Native projects without forcing every coding agent to run directly on the machine that owns the required emulator, simulator, or physical device.

The central architectural distinction is:

> **Agents reason. Runners expose execution capabilities.**

Paperclip should remain the orchestration/control plane. Coding agents should own the task, implementation decisions, and interpretation of results. Remote machines should provide bounded platform-specific capabilities such as:

- building;
- launching;
- testing;
- installing;
- interacting with emulators/simulators;
- interacting with attached physical devices;
- collecting logs;
- capturing screenshots and recordings;
- returning structured test results.

This allows Overmind to coordinate mobile development across multiple machines without introducing unnecessary secondary agents.

---

## 1. Core Architecture

```text
                         PAPERCLIP
                             │
                        Coding Agent
                    owns task + reasoning
                             │
             ┌───────────────┼────────────────┐
             │               │                │
             ▼               ▼                ▼
        Overmind Host    Mobile Runner    Future Runners
        Linux / server      Mac mini      GPU / Windows /
             │               │            browser / ARM
             │               │
        repo / tests    ┌─────┴─────┐
                        │           │
                        ▼           ▼
                 iOS Simulator   Physical Devices
                                  ├── iPhone
                                  └── Android
```

The agent should not care which specific computer performs a task.

It should request a capability.

Example:

```text
mobile.build(platform="ios")
mobile.test(platform="ios", target="simulator")
mobile.test(platform="android", target="physical")
```

The runner resolves that request against its local toolchain and attached devices.

---

## 2. Agent vs. Runner

This distinction is foundational.

### Agent

The agent:

- understands the feature request;
- edits code;
- chooses an implementation;
- interprets failures;
- decides what to try next;
- reviews test evidence;
- determines whether additional validation is needed.

### Runner

The runner:

- executes commands;
- owns platform-specific SDKs;
- owns emulators/simulators;
- owns attached devices;
- returns logs, artifacts, screenshots, and test results;
- exposes a stable capability interface.

The runner is primarily deterministic infrastructure.

A separate reasoning agent should not be introduced simply because execution happens on a different machine.

---

## 3. Initial Hardware Layout

The first mobile runner can use existing hardware.

### `mobile-runner-01`

Initial target:

```text
Spare Intel Mac mini
├── macOS
├── Xcode
├── iOS Simulator
├── Flutter
├── React Native / Node tooling
├── Android SDK
├── Android emulator where practical
├── Tailscale
├── runner service
├── spare iPhone over USB
└── spare Android phone over USB
```

This machine becomes a dedicated remote mobile-development bench.

The physical devices can remain plugged in and configured for development.

---

## 4. Intel Mac Mini Decision

An Apple Silicon Mac mini is **not required for the initial implementation**.

The existing Intel Mac mini can be used to prove the architecture as long as it can run the required macOS/Xcode versions for current project targets.

The important distinction is:

> **The Intel machine is sufficient for prototyping, but it should not be treated as the permanent platform assumption.**

Its value is that it allows Overmind to test:

- remote iOS builds;
- simulator control;
- physical iPhone deployment;
- remote Android-device control;
- screenshot/log collection;
- agent-driven debugging;
- runner scheduling;
- capability discovery.

without buying additional hardware.

If Apple eventually drops the required Xcode/iOS support for that machine, the replacement path is simple:

```text
Intel Mac mini
      ↓
Apple Silicon Mac mini
```

The Paperclip workflow and runner API should remain unchanged.

---

## 5. Capability-Based Runner Interface

Paperclip agents should request capabilities rather than target named hardware.

Conceptually:

```yaml
runner: mobile-runner-01

platforms:
  ios:
    build: true
    simulator: true
    physical_device: true

  android:
    build: true
    emulator: true
    physical_device: true

toolchains:
  flutter: true
  react_native: true

devices:
  - id: iphone-test-01
    platform: ios
  - id: android-test-01
    platform: android
```

A task can therefore request:

```yaml
requires:
  - ios.build
  - ios.physical_device
  - camera
```

without caring which machine satisfies the requirement.

This creates a stable architectural seam between orchestration and hardware.

---

## 6. Runner Transport

The initial runner should be reachable privately over Tailscale.

Possible interface styles:

- MCP;
- HTTP/JSON API;
- SSH-backed command wrapper;
- a small custom Paperclip adapter.

The exact transport is secondary.

The important contract is:

```text
agent
  ↓
bounded capability call
  ↓
runner
  ↓
platform command
  ↓
structured result
```

The runner should not expose unrestricted remote shell access unless specifically required.

---

## 7. Example Runner Capabilities

### Build

```text
mobile.build(...)
mobile.clean(...)
mobile.dependencies.install(...)
```

### Simulator / Emulator

```text
mobile.simulator.list(...)
mobile.simulator.boot(...)
mobile.simulator.shutdown(...)
mobile.simulator.reset(...)
```

### Application Lifecycle

```text
mobile.app.install(...)
mobile.app.launch(...)
mobile.app.stop(...)
mobile.app.uninstall(...)
mobile.app.clear_data(...)
```

### Testing

```text
mobile.test.unit(...)
mobile.test.integration(...)
mobile.test.ui(...)
```

### Interaction

```text
mobile.input.tap(...)
mobile.input.type(...)
mobile.input.swipe(...)
```

### Observation

```text
mobile.logs.read(...)
mobile.screenshot.capture(...)
mobile.video.capture(...)
mobile.test.results(...)
mobile.device.status(...)
```

These should be implemented using existing platform tooling rather than bespoke device-control logic wherever possible.

---

## 8. iOS Execution Surface

The Mac runner should expose existing Apple tooling such as:

```text
xcodebuild
xcrun simctl
xcrun devicectl
XCTest / XCUITest
Flutter tooling
React Native tooling
```

This enables:

- iOS builds;
- simulator boot/shutdown;
- app installation;
- application launch;
- simulator screenshots;
- automated UI tests;
- physical-device installation;
- device/process logs;
- deterministic test execution.

The coding agent receives the outputs and decides what they mean.

---

## 9. Android Execution Surface

The runner should expose standard Android tooling such as:

```text
adb
Gradle
Android Emulator
logcat
instrumentation tests
Flutter tooling
React Native tooling
```

This enables:

- APK builds;
- emulator runs;
- physical-device deployment;
- app-data reset;
- process control;
- UI automation;
- screenshots;
- device logs;
- test-result capture.

Android execution may eventually move to the primary Overmind x86 server if that machine provides a better Linux/KVM environment.

The capability contract should remain unchanged.

---

## 10. Basic Development Workflow

A normal feature task should proceed from cheap validation to expensive validation.

```text
Paperclip task
      ↓
Coding Agent
      ↓
isolated Git worktree
      ↓
static analysis
      ↓
unit/component tests
      ↓
native build
      ↓
simulator/emulator validation
      ↓
physical-device validation if required
      ↓
review
      ↓
human attention only if needed
```

Not every change requires an emulator or device run.

The workflow should escalate test cost progressively.

---

## 11. Example Agent Loop

For a mobile feature:

```text
1. Agent edits code.
2. Agent runs static checks.
3. Agent runs unit/widget/component tests.
4. Agent requests iOS simulator build.
5. Runner builds and launches app.
6. Runner executes automated interaction.
7. Runner returns:
   - test result
   - logs
   - screenshot
   - optional recording
8. Agent inspects evidence.
9. Agent modifies code.
10. Repeat until validation passes.
```

This gives the Paperclip agent effectively the same feedback loop it would have if it were directly controlling a local emulator.

---

## 12. Physical Device Workflow

Physical-device testing should be invoked when hardware behavior matters.

Examples include:

- camera;
- Bluetooth;
- NFC;
- USB;
- native inference acceleration;
- permissions;
- thermal behavior;
- device-specific rendering;
- memory pressure;
- background execution;
- sensors.

For projects such as Gather, physical-device testing is particularly important because significant functionality depends on camera capture, native computer-vision libraries, on-device inference, and hardware-specific behavior.

A task may therefore declare:

```yaml
requires_device:
  ios: true
  android: true

reason:
  - camera
  - on_device_inference
```

The agent can then send the same commit to the appropriate runner/device combination.

---

## 13. Visual Review

The runner should treat screenshots and recordings as first-class artifacts.

A validation response might include:

```text
status: failed

artifacts:
  - screenshot.png
  - run.mp4
  - app.log
  - test-results.xml
```

A vision-capable coding/review agent can inspect these artifacts and identify issues such as:

- overlapping UI;
- clipped text;
- incorrect modal state;
- layout breakage;
- missing controls;
- unexpected navigation.

This enables an automated loop:

```text
implement
   ↓
launch
   ↓
interact
   ↓
capture
   ↓
visual review
   ↓
revise
```

---

## 14. When a Second Agent Is Appropriate

Remote execution does not by itself justify a second agent.

Use a separate agent only when the task represents a distinct reasoning role.

Example:

```text
Implementation Agent
        ↓
feature complete
        ↓
Device QA Agent
        ↓
runs independent scenario suite
        ↓
reports findings
        ↓
Implementation Agent
```

This makes sense because QA is an independent review function.

By contrast:

```text
"run this build on the iPhone"
```

is a tool invocation, not a new agent job.

---

## 15. Runner Health and Availability

Each runner should publish:

```text
identity
online/offline state
supported capabilities
tool versions
attached devices
device state
disk availability
queue state
```

Example:

```yaml
runner: mobile-runner-01
status: online

capabilities:
  ios.build: true
  ios.simulator: true
  ios.device: true
  android.build: true
  android.device: true

devices:
  iphone-test-01: ready
  android-test-01: ready
```

Paperclip can then determine whether a task can execute immediately or needs to wait.

---

## 16. Security and Access

The runner should follow the same bounded-tool philosophy used elsewhere in Overmind.

Avoid giving agents unrestricted remote control of the Mac.

Prefer capabilities such as:

```text
build
install
launch
test
logs
screenshot
reset
```

over:

```text
arbitrary root shell
```

Sensitive operations should require explicit approval where necessary.

Runner access should remain private to the Overmind environment, ideally over Tailscale or another authenticated private network.

---

## 17. Git and Workspace Strategy

Coding work should remain Git-based.

The runner should normally execute a specific:

```text
repository
branch/worktree
commit SHA
```

rather than relying on ambiguous mutable state.

Example:

```text
mobile.test(
  project="gather",
  commit="abc123",
  platform="ios",
  target="iphone-test-01"
)
```

This improves:

- reproducibility;
- debugging;
- auditability;
- parallel agent work;
- test-result attribution.

---

## 18. Artifacts

Runner outputs should be attached to the associated Paperclip work item or stored in the appropriate project artifact space.

Possible artifacts include:

```text
build logs
test reports
screenshots
screen recordings
crash logs
device logs
performance traces
compiled packages
```

These outputs should remain associated with the commit and task that produced them.

---

## 19. Generalization Beyond Mobile

The runner abstraction should not be mobile-specific.

The same model can support future execution targets:

```text
android-linux-runner
ios-mac-runner
windows-runner
gpu-runner
browser-runner
arm-runner
cuda-runner
raspberry-pi-runner
```

Paperclip requests capabilities.

The execution infrastructure decides where they run.

This allows Overmind to grow without coupling workflows to individual machines.

---

## 20. Initial MVP

The first implementation should remain small.

### Hardware

- existing Intel Mac mini;
- spare iPhone;
- spare Android phone.

### Networking

- Tailscale.

### Tooling

- Xcode;
- Flutter;
- React Native / Node;
- Android SDK;
- platform command-line tools.

### Runner capabilities

Start with:

```text
health
device list
build
install
launch
test
logs
screenshot
```

Do not initially build an elaborate generalized orchestration platform.

Prove one end-to-end workflow first.

---

## 21. First Proving-Ground Workflow

A good first demonstration:

```text
Paperclip coding task
      ↓
agent edits Gather
      ↓
unit/static checks
      ↓
send commit to mobile-runner-01
      ↓
build iOS
      ↓
install on spare iPhone
      ↓
run one automated test flow
      ↓
capture logs + screenshot
      ↓
return results to agent
      ↓
agent evaluates
```

Then repeat for Android.

If this loop works reliably, expand the runner interface gradually.

---

## 22. Migration Path

The architecture should intentionally survive hardware replacement.

Initial:

```text
mobile-runner-01
2018-class Intel Mac mini
```

Future:

```text
mobile-runner-01
Apple Silicon Mac mini
```

From Paperclip's perspective:

```text
capabilities unchanged
```

The hardware change should require infrastructure reconfiguration, not agent-workflow redesign.

---

## 23. Success Criterion

The mobile-runner architecture succeeds when a Paperclip coding agent can:

```text
write code
      ↓
request platform execution
      ↓
run against simulator/emulator/device
      ↓
receive logs/screenshots/test results
      ↓
reason about failure
      ↓
modify code
      ↓
repeat
```

without the human manually moving between machines or acting as the message bus between the agent and the device.

The human remains responsible for consequential product decisions and tasks that genuinely require physical judgment.

---

## 24. Concise Architecture Principle

> **Paperclip owns work. Agents own reasoning. Runners own environments. Devices provide reality.**

And:

> **Request capabilities, not computers.**

This separation allows Overmind to orchestrate mobile development across changing hardware while keeping agents, projects, and workflows portable.
