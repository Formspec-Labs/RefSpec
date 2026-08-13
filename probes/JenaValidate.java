import java.nio.file.Path;

import org.apache.jena.graph.Graph;
import org.apache.jena.riot.RDFDataMgr;
import org.apache.jena.shacl.ShaclValidator;
import org.apache.jena.shacl.Shapes;
import org.apache.jena.shacl.ValidationReport;

/** Compact API runner used to compare Jena SHACL engine versions. */
public final class JenaValidate {
    private JenaValidate() {}

    public static void main(String[] args) {
        if (args.length != 2) {
            System.err.println("usage: JenaValidate DATA SHAPES");
            System.exit(2);
        }

        long started = System.nanoTime();
        Graph data = RDFDataMgr.loadGraph(Path.of(args[0]).toUri().toString());
        Graph shapeGraph = RDFDataMgr.loadGraph(Path.of(args[1]).toUri().toString());
        Shapes shapes = Shapes.parse(shapeGraph);
        long loaded = System.nanoTime();

        ValidationReport report = ShaclValidator.get().validate(shapes, data);
        long validated = System.nanoTime();

        System.out.printf(
                "engine=jena-shacl data_triples=%d shape_triples=%d "
                        + "load_seconds=%.3f validate_seconds=%.3f total_seconds=%.3f "
                        + "conforms=%s entries=%d%n",
                data.size(),
                shapeGraph.size(),
                seconds(loaded - started),
                seconds(validated - loaded),
                seconds(validated - started),
                report.conforms(),
                report.getEntries().size());
    }

    private static double seconds(long nanoseconds) {
        return nanoseconds / 1_000_000_000.0;
    }
}
