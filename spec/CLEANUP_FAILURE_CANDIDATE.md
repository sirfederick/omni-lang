> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# CP-03 candidate — cleanup order, fallible close, injected acquisition failure and the resource oracle

Status: candidate for Core 1.3.0.0. It sits on the owned slots of `OWNED_SLOTS_CANDIDATE.md` and on `examples/storage/seq.omni`.
It adds no ownership law: a resource is still owned by exactly one place, and `Resource<T>` still has to be consumed.

## 1. Three kinds of ending, kept apart

| Kind | Who decides | What it can report |
|---|---|---|
| Automatic cleanup | the compiler, on every exit path | nothing: it is only offered to types whose release cannot fail (`Buffer`) |
| Explicit infallible consumption | the programmer (`Dispose`) | a report value; there is no error channel |
| Explicit fallible close | the programmer (`Close`) | an error the caller receives and must handle |

A destructor never swallows an error. A type whose release can fail is **not** given automatic cleanup: it has to be closed by a call whose
`Result` the caller consumes (`E_RESULT_FLOW` / `E_RESOURCE_LEAK` already refuse to drop it).

## 2. `Close`: the fallible close

```omni
pub trait Close {
  // Consumes the element. Ok(n): n units were released. Err(code): the close failed with `code`.
  func finish(x Resource<Self>) Result<u32,u32> !{memory.write}
}
```

Decisions (the owner of the resource and of the error):

1. **`finish` always consumes the element.** The caller does not get the resource back on `Err`. The implementation releases whatever it can and reports
   what it could not; the failed element is gone, as a POSIX `close(2)` descriptor is gone after `EIO`. This is what makes "close twice" impossible
   without a second law of ownership.
2. **The error belongs to the caller of `finish`.** It is a value in the `Result`, so it cannot be dropped silently.
3. **Remaining elements of a collection are still closed.** `Seq.close_all` closes every element, last to first, even after a failure, then releases the
   buffer. It never leaves live elements behind an error and never stops half way holding owners.
4. **The first error wins, none is hidden.** `CloseReport { closed, failed, first, trace }`: `closed` counts successes, `failed` counts failures,
   `first` is the code of the first failure (0 if none), `trace` is an order-sensitive digest of the codes seen so the order is observable.
   `failed == 0` is success. A caller that wants to stop at the first failure composes `pop` and `Close.finish` itself.

## 3. Defined order

- Elements of a `Seq` are closed **last to first**.
- The buffer of a `Seq` is released **after** its last element; `slots.release` refuses (`E_SLOT_OCCUPIED`) while any cell is occupied.
- Automatic `Buffer` cleanup runs on return, break, continue and match arms in the reverse order of declaration. This is observable by the audit of §5.

## 4. Injected acquisition failure

`OMNI_FAIL_AT=N` (environment of the evaluator and of the native runtime): the N-th **acquisition point** of the run fails with the host
out-of-memory outcome (3). Acquisition points, in order of occurrence: `buffer.alloc`, `buffer.grow`, `slots.alloc`, `slots.grow`. `N` counts from 1; an
unset or 0 value injects nothing. The failure is the ordinary typed failure of the operation (a `Result::Err`), so the program handles it with the same
code it would use for real exhaustion. The catalogue is closed: adding an acquisition point means adding it to this list and to the sweep test.

## 5. The resource oracle

`OMNI_RESOURCE_AUDIT=1` makes the run print, on stderr, one line per event and a final summary:

```
audit acq <slot>
audit rel <slot>
audit summary acquired=A released=R live=L
```

and the two misuses the runtime already detects are now **distinct faults**:

| Fault | Meaning |
|---|---|
| `E_RESOURCE_HANDLE` | the handle was never issued (forged or out of range) |
| `E_RESOURCE_DOUBLE_RELEASE` | `release` of a handle that was already released |
| `E_RESOURCE_STALE_USE` | any other use of a released handle (a release done too early) |
| `E_SLOT_OCCUPIED` | a buffer released while it still owns resources (a premature release of the container) |

The oracle classifies a run as: **leak** (`live > 0` in the summary), **double release** (`E_RESOURCE_DOUBLE_RELEASE`), **premature release**
(`E_RESOURCE_STALE_USE` or `E_SLOT_OCCUPIED`), or clean. `acquired == released` alone is not accepted as proof: the sweep asserts the class, and the
mutants of the library each have to be classified as the class they model.

## 6. What this does not claim

- Cancellation: the runtime has a cancel flag only in host invocation mode. CP-03 states the path (a cancelled invocation is a failure, not a cleanup
  guarantee, row 3.6) and does not add structured cancellation, which is CP-12/CP-14.
- A trap or an external abort is not announced as guaranteed cleanup.
- Hosted profile only, as the slots.
