#!/usr/bin/env python3
"""CP-01 / CP-05: Resource<T>, Borrow<T> and BorrowMut<T> where T is a generic parameter or `Self` (spec/GENERIC_RESOURCE_CANDIDATE.md).

Reproducer, measured on 120a24b before the change:
* `func hold<T>(x Resource<T>) Resource<T>` instantiated for a nominal resource        -> E_RESOURCE_TYPE
* `struct Holder<T> { item Option<Resource<T>> }` instantiated for a nominal resource  -> E_RESOURCE_TYPE
* `trait Own { func give(v Resource<Self>) u64 }` implemented for a nominal resource   -> E_TRAIT_METHOD (parameter 0 differs)
The law is unchanged: the argument is replaced by the nominal record it stands for before any ownership rule runs, so every existing rule (exact-once
consumption, move, private seal/unseal/peek, distinct nominal identities) applies to the instance; a generic parameter never becomes a way to see inside a
resource declared elsewhere. Positive programs run in the evaluator and natively and must agree.
"""
from __future__ import annotations
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import OMNI, proc

TOK = ('struct Tok { h u64 }\n'
       'func mint(n u64) Resource<Tok> { return resource.seal(Tok { h: n }) }\n'
       'func eat(f Resource<Tok>) u64 { let r Tok = resource.unseal(move(f)); return r.h }\n')
OTHER = ('struct Other { h u64 }\n'
         'func mint_other(n u64) Resource<Other> { return resource.seal(Other { h: n }) }\n'
         'func eat_other(f Resource<Other>) u64 { let r Other = resource.unseal(move(f)); return r.h }\n')


class GenericResourceTests(ContainerCase):
    def test_a_generic_function_passes_a_nominal_resource_through(self):
        self.both(self.source(
            TOK + 'func hold<T>(x Resource<T>) Resource<T> { return move(x) }\n'
            'func main() u32 { if eat(hold<Tok>(hold<Tok>(mint(42u64)))) == 42u64 { return 42u32 } return 1u32 }\n'))

    def test_two_instantiations_are_distinct_types(self):
        self.both(self.source(
            TOK + OTHER + 'func hold<T>(x Resource<T>) Resource<T> { return move(x) }\n'
            'func main() u32 {\n  let a u64 = eat(hold<Tok>(mint(40u64)))\n  let b u64 = eat_other(hold<Other>(mint_other(2u64)))\n'
            '  if a + b == 42u64 { return 42u32 } return 1u32\n}\n'))
        self.rejected(TOK + OTHER + 'func hold<T>(x Resource<T>) Resource<T> { return move(x) }\n'
                      'func main() u32 { if eat(hold<Other>(mint_other(1u64))) == 1u64 { return 0u32 } return 1u32 }\n', b'E_TYPE')

    def test_a_generic_struct_holds_a_resource_of_its_parameter_and_gives_it_back_once(self):
        self.both(self.source(
            TOK + 'struct Holder<T> { item Option<Resource<T>> }\n'
            'func make<T>(x Resource<T>) Holder<T> { return Holder<T> { item: Some<Resource<T>>(move(x)) } }\n'
            'func main() u32 {\n  let h Holder<Tok> = make<Tok>(mint(42u64))\n'
            '  match h.item { Some(t) { if eat(move(t)) == 42u64 { return 42u32 } return 1u32 } None { return 2u32 } }\n}\n'))

    def test_a_resource_of_a_generic_nominal_instance_goes_through_a_generic_function(self):
        self.both(self.source(
            'func hold<T>(x Resource<T>) Resource<T> { return move(x) }\n'
            'func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<u32,alloc.Heap>(4u32)\n'
            '  match c { Ok(v) {\n    let w = hold<vec.Vec<u32,alloc.Heap>>(move(v))\n    let d = vec.destroy<u32,alloc.Heap>(move(w))\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_the_argument_may_be_a_generic_instance_that_depends_on_the_callers_own_parameter(self):
        # inside `relay<U>` the argument `vec.Vec<U,alloc.Heap>` is not resolved yet when `hold<T>` is substituted: its generic arguments must travel with the name
        self.both(self.source(
            'struct Cell<T> { b Resource<Buffer> }\n'
            'func make<T>() Result<Resource<Cell<T>>,u32> !{memory.write} {\n  let a = buffer.alloc(8u32)\n'
            '  match a { Ok(b) {\n    let c Cell<T> = Cell<T> { b: move(b) }\n    return Ok<Resource<Cell<T>>,u32>(resource.seal(move(c)))\n'
            '  } Err(e) { return Err<Resource<Cell<T>>,u32>(e) } }\n}\n'
            'func drop<T>(c Resource<Cell<T>>) u32 !{memory.write} {\n  let i Cell<T> = resource.unseal(move(c))\n  return buffer.release(move(i.b))\n}\n'
            'func hold<T>(x Resource<T>) Resource<T> { return move(x) }\n'
            'func relay<U>(x Resource<Cell<U>>) Resource<Cell<U>> { return hold<Cell<U>>(move(x)) }\n'
            'func main() u32 !{memory.write} {\n  let c = make<u32>()\n'
            '  match c { Ok(v) {\n    let w = relay<u32>(move(v))\n    let d u32 = drop<u32>(move(w))\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_a_trait_method_takes_the_implementing_resource_by_self(self):
        self.both(self.source(
            TOK + 'trait Own { func give(v Resource<Self>) u64 }\n'
            'impl Own for Tok { func give(v Resource<Tok>) u64 { return eat(move(v)) } }\n'
            'func give_it<T: Own>(v Resource<T>) u64 { return Own.give<T>(move(v)) }\n'
            'func main() u32 { if give_it<Tok>(mint(42u64)) == 42u64 { return 42u32 } return 1u32 }\n'))

    def test_the_impl_must_spell_the_same_resource_the_trait_names(self):
        self.rejected(TOK + OTHER + 'trait Own { func give(v Resource<Self>) u64 }\n'
                      'impl Own for Tok { func give(v Resource<Other>) u64 { return eat_other(move(v)) } }\n'
                      'func main() u32 { return 0u32 }\n', b'E_TRAIT_METHOD')

    def test_borrows_of_the_parameter_are_lent_like_any_nominal_borrow(self):
        self.both(self.source(
            TOK + 'func lend<T>(x Borrow<T>) u32 { return 7u32 }\nfunc lend_mut<T>(x BorrowMut<T>) u32 { return 5u32 }\n'
            'func main() u32 {\n  let r = mint(30u64)\n  let a u32 = lend<Tok>(borrow(r))\n  let m = mint(1u64)\n'
            '  let b u32 = lend_mut<Tok>(borrow_mut(m))\n  let x u64 = eat(move(r))\n  let y u64 = eat(move(m))\n'
            '  if x + y == 31u64 { return a + b + 30u32 } return 1u32\n}\n'))


class NestedGenericInstanceTests(ContainerCase):
    """Found while writing the resource tests, and independent of resources: a generic function that calls another generic with an instance of a generic
    struct built from its own parameter (`id<Plain<U>>` inside `relay<U>`) was refused with E_TYPE 'tipo generico nominal inexistente'."""

    def test_a_generic_calls_another_generic_with_an_instance_of_its_own_parameter(self):
        self.both(self.source(
            'struct Plain<T> { n u32 }\nfunc id<T>(x T) T { return x }\n'
            'func relay<U>(x Plain<U>) Plain<U> { return id<Plain<U>>(x) }\n'
            'func main() u32 { let p Plain<u32> = Plain<u32> { n: 42u32 }\n  let q = relay<u32>(p)\n  return q.n }\n'))

    def test_an_instance_that_exists_only_inside_the_generated_body_is_created_and_found(self):
        # nothing outside `build<V>` mentions Plain<u64>: its instance is born while the generated body is processed
        self.both(self.source(
            'struct Plain<T> { n u32 }\nfunc id<T>(x T) T { return x }\n'
            'func build<V>() u32 {\n  let p Plain<V> = Plain<V> { n: 40u32 }\n  let q = id<Plain<V>>(p)\n  return q.n + 2u32\n}\n'
            'func main() u32 { return build<u64>() }\n'))

    def test_an_enum_instance_that_exists_only_inside_the_generated_body_is_created_and_found(self):
        self.both(self.source(
            'enum Pick<T> { Just(T), Nothing }\nfunc id<T>(x T) T { return x }\n'
            'func build<V>() u32 {\n  let k Pick<V> = Pick.Nothing<V>()\n  let r = id<Pick<V>>(k)\n  match r { Just(v) { return 1u32 } Nothing { return 42u32 } }\n}\n'
            'func main() u32 { return build<u64>() }\n'))

    def test_the_same_chain_two_levels_deep_and_with_two_different_arguments(self):
        self.both(self.source(
            'struct Plain<T> { n u32 }\nstruct Wrap<T> { inner Plain<T> }\nfunc id<T>(x T) T { return x }\n'
            'func level1<U>(x Wrap<U>) Wrap<U> { return id<Wrap<U>>(x) }\nfunc level2<V>(x Wrap<V>) Wrap<V> { return level1<V>(x) }\n'
            'func main() u32 {\n  let a Wrap<u32> = Wrap<u32> { inner: Plain<u32> { n: 40u32 } }\n  let b Wrap<u64> = Wrap<u64> { inner: Plain<u64> { n: 2u32 } }\n'
            '  let c = level2<u32>(a)\n  let d = level2<u64>(b)\n  return c.inner.n + d.inner.n\n}\n'))


class GenericResourceLawTests(ContainerCase):
    """What the instance must still refuse: the substitution happens before the ownership rules, so none of them is bypassed."""

    def test_a_generic_function_that_drops_the_resource_is_unconsumed(self):
        self.rejected(TOK + 'func leak<T>(x Resource<T>) u32 { return 0u32 }\n'
                      'func main() u32 { return leak<Tok>(mint(1u64)) }\n', b'E_RESOURCE_UNCONSUMED')

    def test_a_generic_function_cannot_use_a_moved_resource(self):
        self.rejected(TOK + 'func twice<T>(x Resource<T>) Resource<T> { let a = move(x)\n  return move(x) }\n'
                      'func main() u32 { let r = twice<Tok>(mint(1u64))\n  let v u64 = eat(move(r))\n  return 0u32 }\n', b'E_RESOURCE_MOVED')

    def test_an_argument_that_is_not_a_nominal_record_is_refused(self):
        self.rejected('func hold<T>(x Resource<T>) Resource<T> { return move(x) }\n'
                      'func main() u32 { let r = hold<u32>(1u32)\n  return 0u32 }\n', b'E_GENERIC_CONSTRAINT')

    def test_a_record_that_is_not_a_single_u64_handle_is_not_a_resource(self):
        self.rejected('struct Pair { a u32, b u32 }\nfunc hold<T>(x Resource<T>) Resource<T> { return move(x) }\n'
                      'func main() u32 { return 0u32 }\nfunc bad(p Resource<Pair>) u32 { return 0u32 }\n', b'E_RESOURCE_TYPE')

    def test_a_generic_function_cannot_open_a_resource_declared_in_another_module(self):
        # `steal` is written in this module, so it has no seal/unseal authority over vec.Vec, whatever the parameter stands for.
        self.rejected('func steal<T>(x Resource<T>) u32 { let inner T = resource.unseal(move(x))\n  return 0u32 }\n'
                      'func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<u32,alloc.Heap>(1u32)\n'
                      '  match c { Ok(v) { return steal<vec.Vec<u32,alloc.Heap>>(move(v)) } Err(e) { return e } }\n}\n', b'E_RESOURCE_PRIVATE')

    def test_a_generic_function_cannot_peek_at_a_resource_declared_in_another_module(self):
        (self.dir / 'tok.omni').write_text('module tok\npub struct Tok { h u64 }\npub func mint(n u64) Resource<Tok> { return resource.seal(Tok { h: n }) }\n'
                                           'pub func eat(f Resource<Tok>) u64 { let r Tok = resource.unseal(move(f)); return r.h }\n', encoding='utf-8')
        self.rejected('import tok "tok.omni"\nfunc look<T>(x Borrow<T>) u64 { let r T = resource.peek(x)\n  return 0u64 }\n'
                      'func main() u32 {\n  let r = tok.mint(1u64)\n  let v u64 = look<tok.Tok>(borrow(r))\n  let w u64 = tok.eat(move(r))\n  return 0u32\n}\n', b'E_RESOURCE_PRIVATE')

    def test_a_generic_function_cannot_mint_a_resource_of_another_module(self):
        (self.dir / 'tok.omni').write_text('module tok\npub struct Tok { h u64 }\n'
                                           'pub func eat(f Resource<Tok>) u64 { let r Tok = resource.unseal(move(f)); return r.h }\n', encoding='utf-8')
        self.rejected('import tok "tok.omni"\nfunc forge<T>(h T) Resource<T> { return resource.seal(h) }\n'
                      'func main() u32 {\n  let r = forge<tok.Tok>(tok.Tok { h: 1u64 })\n  let v u64 = tok.eat(move(r))\n  return 0u32\n}\n', b'E_RESOURCE_PRIVATE')


if __name__ == '__main__':
    unittest.main()
