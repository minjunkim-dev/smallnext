fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("{}", smallnext_api::api_document().to_pretty_json()?);
    Ok(())
}
