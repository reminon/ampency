using System;
using System.IO;
using GameArchives;
using GameArchives.Ark;

class Program {
    static void Main(string[] args) {
        if (args.Length < 2) {
            Console.WriteLine("Usage: ArkExtract <ark_file> <output_dir>");
            return;
        }
        string arkFile = args[0];
        string outDir = args[1];

        Console.WriteLine($"Opening {arkFile}...");
        var pkg = PackageReader.ReadPackageFromFile(arkFile);
        Console.WriteLine($"Package type: {pkg.GetType().Name}");
        ExtractDir(pkg.RootDirectory, outDir);
        Console.WriteLine("Done.");
    }

    static void ExtractDir(IDirectory dir, string outPath) {
        Directory.CreateDirectory(outPath);
        foreach (var file in dir.Files) {
            string dest = Path.Combine(outPath, file.Name);
            Console.WriteLine($"  {file.Name}");
            using var src = file.GetStream();
            using var dst = File.Create(dest);
            src.CopyTo(dst);
        }
        foreach (var subdir in dir.Dirs) {
            ExtractDir(subdir, Path.Combine(outPath, subdir.Name));
        }
    }
}
