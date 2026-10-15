fn main() {
    // sqlx::migrate! must embed newly added migrations when compiler outputs are cached.
    println!("cargo:rerun-if-changed=migrations");
}
