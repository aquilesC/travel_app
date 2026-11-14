// swift-tools-version: 6.0
// TripsKit: everything in the iPhone app that doesn't need Apple-only frameworks.
// Builds and tests on Linux too (`ios/test.sh`), so the logic is checked without a Mac.
import PackageDescription

let package = Package(
    name: "TripsKit",
    platforms: [.iOS(.v18), .macOS(.v15)],
    products: [
        .library(name: "TripsAPI", targets: ["TripsAPI"]),
        .library(name: "TripsKit", targets: ["TripsKit"]),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-openapi-generator", from: "1.10.0"),
        .package(url: "https://github.com/apple/swift-openapi-runtime", from: "1.8.0"),
        .package(url: "https://github.com/apple/swift-openapi-urlsession", from: "1.1.0"),
        // SHA-256 on Linux too (on Apple platforms it re-exports CryptoKit).
        .package(url: "https://github.com/apple/swift-crypto", from: "3.0.0"),
    ],
    targets: [
        // Generated from api/openapi.json (the contract with the website) at build time.
        .target(
            name: "TripsAPI",
            dependencies: [
                .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
                .product(name: "OpenAPIURLSession", package: "swift-openapi-urlsession"),
            ],
            plugins: [.plugin(name: "OpenAPIGenerator", package: "swift-openapi-generator")]
        ),
        .target(name: "TripsKit", dependencies: [
            "TripsAPI",
            .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
            .product(name: "OpenAPIURLSession", package: "swift-openapi-urlsession"),
            .product(name: "Crypto", package: "swift-crypto"),
        ]),
        .testTarget(name: "TripsKitTests", dependencies: ["TripsKit"]),
    ]
)
