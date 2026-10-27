import CryptoKit
import Foundation

// File Provider placeholders must be read through macOS file coordination.
guard CommandLine.arguments.count == 2 else { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let coordinator = NSFileCoordinator(filePresenter: nil)
var coordinationError: NSError?
var readError: Error?
var digest: String?
coordinator.coordinate(readingItemAt: url, options: [], error: &coordinationError) { location in
    do {
        let data = try Data(contentsOf: location)
        digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    } catch {
        readError = error
    }
}
guard coordinationError == nil, readError == nil, let result = digest else {
    fputs("No se ha podido leer el archivo mediante File Provider.\n", stderr)
    exit(1)
}
print(result)
