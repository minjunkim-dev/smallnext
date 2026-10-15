// swift-tools-version: 6.0
import PackageDescription

// App logic that runs without a simulator, tested on macOS with `swift test`.
let package = Package(
    name: "SmallnextCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "SmallnextCore", targets: ["SmallnextCore"]),
    ],
    dependencies: [
        .package(url: "https://github.com/groue/GRDB.swift.git", exact: "7.11.1"),
    ],
    targets: [
        .target(name: "SmallnextCore", dependencies: [.product(name: "GRDB", package: "GRDB.swift")]),
        .testTarget(
            name: "SmallnextCoreTests",
            dependencies: ["SmallnextCore", .product(name: "GRDB", package: "GRDB.swift")]
        ),
    ]
)
